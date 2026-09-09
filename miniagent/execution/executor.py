from miniagent.gates.pipeline import GatePipeline, GateResult
from miniagent.state.models import AgentState, ToolAction, ToolResult
from miniagent.tools.base import ToolContext
from miniagent.tools.registry import ToolRegistry


class Executor:
    def __init__(self, registry: ToolRegistry, context: ToolContext, gates: GatePipeline):
        self.registry = registry
        self.context = context
        self.gates = gates

    def authorize(self, action: ToolAction, state: AgentState) -> GateResult:
        return self.gates.check(action, state)

    def execute_authorized(self, action: ToolAction) -> ToolResult:
        """Runtime calls this only after authorization and persisting the reservation."""
        tool = self.registry.get(action.tool)
        if tool is None:
            return ToolResult(success=False, error="Unknown tool")
        try:
            args = tool.args_model.model_validate(action.arguments)
            result = tool.execute(args, self.context)
            if len(result.output) > self.context.output_limit:
                result.output = result.output[:self.context.output_limit]
                result.metadata["truncated"] = True
            return result
        except (OSError, ValueError, RuntimeError) as error:
            return ToolResult(success=False, error=str(error)[:1200])
