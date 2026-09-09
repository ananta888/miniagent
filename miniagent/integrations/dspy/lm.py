from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
import time

import dspy

from miniagent.model.base import ModelBackend
from miniagent.state.files import append_json
from miniagent.state.models import ModelConfig


@dataclass
class InferenceBudget:
    max_calls: int = 100
    max_tokens: int = 200000
    max_seconds: float = 900.0
    calls: int = 0
    tokens: int = 0
    started: float = field(default_factory=time.monotonic)
    lock: RLock = field(default_factory=RLock, repr=False)


class BackendLM(dspy.BaseLM):
    """Any configurable text ModelBackend as a typed DSPy LM, without an API server."""
    forward_contract = "typed_lm"

    def __init__(self, backend: ModelBackend, config: ModelConfig, budget: InferenceBudget | None = None,
                 log_path: Path | None = None):
        super().__init__(model=config.model, temperature=config.temperature, max_tokens=config.max_new_tokens,
                         cache=False, num_retries=0)
        self.backend, self.config = backend, config
        self.budget = budget or InferenceBudget()
        self.log_path = log_path

    def __deepcopy__(self, memo):
        result = self.copy()
        memo[id(self)] = result
        return result  # copies share weights, serialization lock, and the total budget

    def forward(self, request: dspy.LMRequest) -> dspy.LMResponse:
        if request.tools or any(part.type != "text" for message in request.messages for part in message.parts):
            raise ValueError("BackendLM accepts text only; tool authority remains in the runtime")
        if request.config.n not in (None, 1):
            raise ValueError("BackendLM supports one bounded completion per request")
        for name in ("top_p", "stop", "logprobs", "response_format", "reasoning", "tool_choice"):
            if getattr(request.config, name) is not None:
                raise ValueError(f"BackendLM does not support the request option: {name}")
        prompt = "\n\n".join((message.text or "") if len(request.messages) == 1 else
                              f"{message.role.upper()}\n{message.text or ''}" for message in request.messages)
        rollout = request.config.extensions.get("rollout_id", 0) or 0
        config = self.config.model_copy(update={
            "temperature": request.config.temperature if request.config.temperature is not None else self.config.temperature,
            "max_new_tokens": min(request.config.max_tokens or self.config.max_new_tokens, self.config.max_new_tokens),
            "seed": (self.config.seed + int(rollout)) % 2147483648,
        })
        config = ModelConfig.model_validate(config.model_dump())
        reservation = config.max_context_tokens + config.max_new_tokens
        with self.budget.lock:
            budget = self.budget
            if (budget.calls >= budget.max_calls or budget.tokens + reservation > budget.max_tokens
                    or time.monotonic() - budget.started >= budget.max_seconds):
                raise RuntimeError("DSPy local inference budget exhausted")
            budget.calls += 1
            budget.tokens += reservation
            previous = getattr(self.backend, "config", None)
            if previous is not None:
                self.backend.config = config
            try:
                response = self.backend.generate(prompt)
            finally:
                if previous is not None:
                    self.backend.config = previous
            budget.tokens += response.input_tokens + response.output_tokens - reservation
            if response.input_tokens > config.max_context_tokens or response.output_tokens > config.max_new_tokens:
                raise RuntimeError("DSPy backend exceeded the configured token allowance")
            if self.log_path:
                append_json(self.log_path, {"call": budget.calls, "prompt": prompt, "response": response.text,
                                           "input_tokens": response.input_tokens, "output_tokens": response.output_tokens})
        return dspy.LMResponse.from_text(response.text, model=self.model, usage={
            "prompt_tokens": response.input_tokens, "completion_tokens": response.output_tokens,
            "total_tokens": response.input_tokens + response.output_tokens,
        }, cost=0.0)

    def dump_state(self):
        from miniagent.model.transformers_model import TransformersBackend
        if not isinstance(self.backend, TransformersBackend):
            raise ValueError("Only TransformersBackend can be reconstructed; export prompt data for other backends")
        return {**super().dump_state(), "model_config": self.config.model_dump()}

    @classmethod
    def load_state(cls, state, **kwargs):
        from miniagent.model.transformers_model import TransformersBackend
        config = ModelConfig.model_validate(state["model_config"])
        return cls(TransformersBackend(config), config)
