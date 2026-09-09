from collections.abc import Callable

from miniagent.execution.executor import Executor
from miniagent.gates.pipeline import (ArgumentGate, BudgetGate, CommandGate, CompletionGate, FailureGate,
                                     GatePipeline, LoopGate, PathGate, SchemaGate, StepGate, ToolGate)
from miniagent.loop import AgentLoop
from miniagent.model.base import ModelBackend
from miniagent.parsing.json_parser import ParserPipeline, StrictJSONParser
from miniagent.parsing.action_parser import ActionParser
from miniagent.parsing.fenced_json_parser import FencedJSONParser
from miniagent.parsing.tool_recovery_parser import ToolRecoveryParser
from miniagent.prompts.builder import PromptBuilder
from miniagent.prompts.strategy import ArtifactPromptStrategy, PromptArtifact, PromptStrategy
from miniagent.state.manager import StateManager
from miniagent.state.models import AgentState, ModelConfig
from miniagent.tools.base import ToolContext, workspace_path
from miniagent.tools.list_files import ListFiles
from miniagent.tools.read_file import ReadFile
from miniagent.tools.registry import ToolRegistry
from miniagent.tools.shell import Shell
from miniagent.tools.write_file import WriteFile


def local_backend(config: ModelConfig) -> ModelBackend:
    from miniagent.model.transformers_model import TransformersBackend
    return TransformersBackend(config)


class Runtime:
    """Composition root: explicit components, no discovery or global registry."""

    def __init__(self, manager: StateManager, model: ModelBackend | None = None,
                 backend_factory: Callable[[ModelConfig], ModelBackend] = local_backend,
                 prompt_strategy_factory: Callable[[ToolRegistry], PromptStrategy] | None = None,
                 should_pause: Callable[[], bool] | None = None):
        self.manager = manager
        self.model = model
        self.backend_factory = backend_factory
        self.prompt_strategy_factory = prompt_strategy_factory
        self.should_pause = should_pause

    def run(self) -> AgentState:
        with self.manager.lock():
            state = self.manager.recover()
            if state.status != "running":
                return state
            tools = [ReadFile(), ListFiles()]
            if state.policy.write_paths:
                tools.append(WriteFile())
            if state.policy.commands:
                tools.append(Shell())
            registry = ToolRegistry(tools)
            context = ToolContext(self.manager.run_dir / "workspace", policy=state.policy,
                                  deadline=state.started_at + state.limits.max_runtime_seconds)
            execution_gates = GatePipeline([
                SchemaGate(), ToolGate(registry), ArgumentGate(registry), PathGate(context),
                CommandGate(), BudgetGate(), FailureGate(), LoopGate(),
            ])
            gates = GatePipeline([*execution_gates.gates, StepGate(), CompletionGate(context)])
            executor = Executor(registry, context, execution_gates)
            # Backend construction is lazy: status and completed resume need no model.
            model = self.model or self.backend_factory(state.model_config_saved)
            prompts = self.prompt_strategy_factory(registry) if self.prompt_strategy_factory else PromptBuilder(registry)
            if state.options.prompt_artifact:
                path = workspace_path(self.manager.run_dir, state.options.prompt_artifact)
                prompts = ArtifactPromptStrategy(prompts, PromptArtifact.load(path))
            loop = AgentLoop(self.manager, model, ActionParser(ParserPipeline([StrictJSONParser(), FencedJSONParser(), ToolRecoveryParser()])),
                             gates, executor, prompts, self.should_pause)
            return loop.run(state)
