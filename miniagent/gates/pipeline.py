import json
import time
from dataclasses import dataclass
from typing import Protocol

from pydantic import ValidationError

from miniagent.state.models import ACTION_ADAPTER, Action, AgentState, FinalAction, PlanAction, StrictModel, ToolAction
from miniagent.tools.base import ToolContext, workspace_path
from miniagent.tools.registry import ToolRegistry


class GateResult(StrictModel):
    allowed: bool
    reason: str | None = None
    terminal: bool = False


class Gate(Protocol):
    def check(self, action: Action, state: AgentState) -> GateResult: ...


def blocked(reason: str, *, terminal: bool = False) -> GateResult:
    return GateResult(allowed=False, reason=reason, terminal=terminal)


def signature(action: ToolAction) -> str:
    return json.dumps([action.tool, action.arguments], sort_keys=True, separators=(",", ":"))


class SchemaGate:
    def check(self, action: Action, state: AgentState) -> GateResult:
        try:
            ACTION_ADAPTER.validate_python(action.model_dump())
        except (ValidationError, AttributeError):
            return blocked("Invalid action schema")
        return GateResult(allowed=True)


@dataclass
class ToolGate:
    registry: ToolRegistry

    def check(self, action: Action, state: AgentState) -> GateResult:
        if isinstance(action, ToolAction) and self.registry.get(action.tool) is None:
            return blocked(f"Unknown tool: {action.tool}")
        return GateResult(allowed=True)


@dataclass
class ArgumentGate:
    registry: ToolRegistry

    def check(self, action: Action, state: AgentState) -> GateResult:
        if isinstance(action, ToolAction):
            tool = self.registry.get(action.tool)
            if tool is None:
                return blocked("Unknown tool")
            try:
                tool.args_model.model_validate(action.arguments)
            except ValidationError as error:
                return blocked(f"Invalid arguments: {error.errors(include_input=False)[0]['msg']}")
        return GateResult(allowed=True)


@dataclass
class PathGate:
    context: ToolContext

    def check(self, action: Action, state: AgentState) -> GateResult:
        if isinstance(action, ToolAction):
            try:
                workspace_path(self.context.workspace, action.arguments.get("path", "."))
            except (ValueError, OSError, RuntimeError, TypeError) as error:
                return blocked(f"Invalid path: {error}")
        return GateResult(allowed=True)


class BudgetGate:
    def check(self, action: Action, state: AgentState) -> GateResult:
        limits = state.limits
        if time.time() - state.started_at >= limits.max_runtime_seconds:
            return blocked("Runtime deadline reached", terminal=True)
        if state.iteration > limits.max_iterations or state.token_budget_used > limits.max_tokens:
            return blocked("Model budget reached", terminal=True)
        if isinstance(action, ToolAction) and state.tool_calls >= limits.max_tool_calls:
            return blocked("Tool budget reached", terminal=True)
        return GateResult(allowed=True)


class FailureGate:
    def check(self, action: Action, state: AgentState) -> GateResult:
        if state.consecutive_failures >= state.limits.max_consecutive_failures:
            return blocked("Consecutive tool failure limit reached", terminal=True)
        return GateResult(allowed=True)


class LoopGate:
    def check(self, action: Action, state: AgentState) -> GateResult:
        if (isinstance(action, ToolAction) and signature(action) == state.last_action
                and state.repeated_action_count >= state.limits.max_repeated_actions):
            return blocked("Repeated action and result limit reached", terminal=True)
        return GateResult(allowed=True)


class StepGate:
    def check(self, action: Action, state: AgentState) -> GateResult:
        if isinstance(action, PlanAction):
            return GateResult(allowed=True) if not state.steps else blocked("Initial plan already exists")
        if isinstance(action, ToolAction):
            step = state.current_step
            if step is None:
                return blocked("No pending plan step")
            expected = ToolAction(type="tool", tool=step.proposal.tool, arguments=step.proposal.arguments)
            if signature(action) != signature(expected):
                return blocked("Tool and arguments must match CURRENT STEP")
        return GateResult(allowed=True)


class CompletionGate:
    def check(self, action: Action, state: AgentState) -> GateResult:
        if isinstance(action, FinalAction):
            if not state.steps or state.current_step is not None:
                return blocked("Every plan step needs a successful, complete observation")
            if not state.verified_reads:
                return blocked("At least one complete read_file observation is required")
            if not set(state.required_reads).issubset(state.verified_reads):
                return blocked("Required read_file evidence is missing")
        return GateResult(allowed=True)


class GatePipeline:
    def __init__(self, gates: list[Gate]):
        self.gates = gates

    def check(self, action: Action, state: AgentState) -> GateResult:
        for gate in self.gates:
            result = gate.check(action, state)
            if not result.allowed:
                return result
        return GateResult(allowed=True)
