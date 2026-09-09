from collections.abc import Callable

from miniagent.execution.executor import Executor
from miniagent.gates.pipeline import (ArgumentGate, BudgetGate, CompletionGate, FailureGate,
                                     GatePipeline, LoopGate, PathGate, SchemaGate, StepGate, ToolGate)
from miniagent.loop import AgentLoop
from miniagent.model.base import ModelBackend
from miniagent.parsing.json_parser import ParserPipeline, StrictJSONParser
from miniagent.prompts.builder import PromptBuilder
from miniagent.state.manager import StateManager
from miniagent.state.models import AgentState, ModelConfig
from miniagent.tools.base import ToolContext
from miniagent.tools.list_files import ListFiles
from miniagent.tools.read_file import ReadFile
from miniagent.tools.registry import ToolRegistry


def local_backend(config: ModelConfig) -> ModelBackend:
    from miniagent.model.transformers_model import TransformersBackend
    return TransformersBackend(config)


class Runtime:
    """Composition root: explicit components, no discovery or global registry."""

    def __init__(self, manager: StateManager, model: ModelBackend | None = None,
                 backend_factory: Callable[[ModelConfig], ModelBackend] = local_backend):
        self.manager = manager
        self.model = model
        self.backend_factory = backend_factory

    def run(self) -> AgentState:
        with self.manager.lock():
            state = self.manager.recover()
            if state.status != "running":
                return state
            registry = ToolRegistry([ReadFile(), ListFiles()])
            context = ToolContext(self.manager.run_dir / "workspace")
            execution_gates = GatePipeline([
                SchemaGate(), ToolGate(registry), ArgumentGate(registry), PathGate(context),
                BudgetGate(), FailureGate(), LoopGate(),
            ])
            gates = GatePipeline([*execution_gates.gates, StepGate(), CompletionGate()])
            executor = Executor(registry, context, execution_gates)
            # Backend construction is lazy: status and completed resume need no model.
            model = self.model or self.backend_factory(state.model_config_saved)
            loop = AgentLoop(self.manager, model, ParserPipeline([StrictJSONParser()]),
                             gates, executor, PromptBuilder(registry))
            return loop.run(state)
