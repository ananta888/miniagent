import time
from collections.abc import Callable
from pathlib import Path

from miniagent.execution.executor import Executor
from miniagent.execution.checkpoints import keep_checkpoint
from miniagent.gates.pipeline import GatePipeline, GateResult, blocked, signature
from miniagent.logging.events import EventLog
from miniagent.model.base import ModelBackend, ModelResponse
from miniagent.parsing.json_parser import ParseError
from miniagent.parsing.action_parser import ActionParser
from miniagent.planning.planner import Planner
from miniagent.prompts.strategy import PromptStrategy
from miniagent.state.context import ContextBuilder
from miniagent.state.files import atomic_write
from miniagent.state.manager import StateManager
from miniagent.state.models import Action, AgentState, FinalAction, Observation, PlanAction, ToolAction
from miniagent.state.observations import ObservationStore
from miniagent.tools.base import workspace_digest


class AgentLoop:
    def __init__(self, manager: StateManager, model: ModelBackend, parser: ActionParser,
                 gates: GatePipeline, executor: Executor, prompts: PromptStrategy,
                 should_pause: Callable[[], bool] | None = None):
        self.manager = manager
        self.model = model
        self.parser = parser
        self.gates = gates
        self.executor = executor
        self.prompts = prompts
        self.observations = ObservationStore(manager.run_dir)
        self.context = ContextBuilder(self.observations, executor.context)
        self.events = EventLog(manager.run_dir)
        self.planner = Planner()
        self.should_pause = should_pause or (lambda: False)

    def stop(self, state: AgentState, reason: str, *, failed: bool = False) -> None:
        state.status = "failed" if failed else "blocked"
        state.feedback = reason
        state.finished_at = time.time()
        self.manager.save(state)
        self.events.emit("run_stopped", status=state.status, reason=reason)

    def run(self, state: AgentState) -> AgentState:
        if state.status != "running":
            return state
        if state.pending_action is not None:
            self.recover_tool(state)
        while state.status == "running":
            if self.should_pause():
                self.manager.save(state)
                self.events.emit("run_paused", iteration=state.iteration)
                break
            try:
                proposal = self.runtime_proposal(state)
            except ValueError as error:
                self.stop(state, f"Invalid configured plan: {error}")
                break
            if not self.model_budget_available(state, needs_model=proposal is None):
                break
            context = self.context.build(state) if proposal is None else {}
            if proposal is not None:
                state.iteration += 1
                self.events.emit("runtime_proposal", iteration=state.iteration, kind=proposal.type)
                response = ModelResponse(text=proposal.model_dump_json(), input_tokens=0, output_tokens=0)
            else:
                prompt = self.prompts.build(state, context)
                response = self.call_model(state, prompt)
            if response is None:
                break
            try:
                action = self.parser.parse(response.text, state, context)
            except ParseError as error:
                state.metrics.invalid_actions += 1
                state.parse_failures += 1
                state.feedback = f"Previous response could not be parsed. {error} Do not explain the format."
                if response.output_tokens >= state.model_config_saved.max_new_tokens:
                    state.feedback += " Response reached the output token limit. Keep the action and code concise."
                self.events.emit("parse_failed", iteration=state.iteration)
                if state.parse_failures > state.limits.max_parse_retries:
                    self.stop(state, "Parse retry limit reached")
                else:
                    self.manager.save(state)
                continue
            state.parse_failures = 0
            if self.parser.recovered:
                state.metrics.parser_recoveries += 1
                self.events.emit("parser_recovered", iteration=state.iteration)
            self.events.emit("action_parsed", iteration=state.iteration, parser=self.parser.method, action=action.model_dump())
            decision = self.gates.check(action, state)
            if decision.allowed and isinstance(action, PlanAction):
                decision = self.validate_plan(action, state)
            if not decision.allowed:
                state.metrics.blocked_actions += 1
                state.consecutive_blocks += 1
                state.feedback = decision.reason
                if decision.reason and "Repeated action" in decision.reason:
                    state.metrics.loop_detections += 1
                self.events.emit("gate_blocked", reason=decision.reason)
                if decision.terminal or state.consecutive_blocks >= state.limits.max_blocked_actions:
                    self.stop(state, decision.reason or "Blocked action limit reached")
                else:
                    self.manager.save(state)
                continue
            state.consecutive_blocks = 0
            state.feedback = None
            self.events.emit("gate_passed", iteration=state.iteration)
            if isinstance(action, PlanAction):
                self.planner.apply(action, state)
                self.events.emit("plan_updated")
                self.manager.save(state)
            elif isinstance(action, ToolAction):
                self.execute_tool(action, state)
            elif isinstance(action, FinalAction):
                state.answer = action.answer
                state.status = "completed"
                state.finished_at = time.time()
                self.manager.save(state)
                self.events.emit("run_completed", answer=state.answer)
        return state

    def runtime_proposal(self, state: AgentState) -> Action | None:
        if not state.steps and state.options.planning_strategy == "files":
            return self.planner.initial(state)
        if (state.needs_replan and state.options.repair_strategy == "rewrite"
                and state.policy.write_paths and state.policy.required_verifications):
            return self.planner.repair(state)
        if state.options.execute_plan and not state.needs_replan:
            if state.steps and state.current_step is None:
                return FinalAction(type="final", answer="All planned steps completed with required verification.")
            if state.current_step and state.current_step.proposal.tool != "write_file":
                step = state.current_step.proposal
                return ToolAction(type="tool", tool=step.tool, arguments=step.arguments)
        return None

    def model_budget_available(self, state: AgentState, *, needs_model: bool = True) -> bool:
        config, limits = state.model_config_saved, state.limits
        reservation = config.max_context_tokens + config.max_new_tokens if needs_model else 0
        reason = None
        if time.time() - state.started_at >= limits.max_runtime_seconds:
            reason = "Runtime deadline reached"
        elif state.iteration >= limits.max_iterations:
            reason = "Iteration budget reached"
        elif state.token_budget_used + reservation > limits.max_tokens:
            reason = "Insufficient tokens for a bounded model call"
        elif state.consecutive_failures >= limits.max_consecutive_failures:
            reason = "Consecutive tool failure limit reached"
        if reason:
            self.stop(state, reason)
            return False
        return True

    def call_model(self, state: AgentState, prompt: str) -> ModelResponse | None:
        config = state.model_config_saved
        reservation = config.max_context_tokens + config.max_new_tokens
        state.iteration += 1
        state.metrics.llm_calls += 1
        state.token_budget_used += reservation
        # A crash during inference retains the conservative token reservation.
        self.manager.save(state)
        self.events.emit("llm_called", iteration=state.iteration)
        try:
            response = self.model.generate(prompt)
        except Exception as error:
            self.stop(state, f"Model error: {type(error).__name__}: {str(error)[:1000]}", failed=True)
            return None
        actual = response.input_tokens + response.output_tokens
        state.token_budget_used += actual - reservation
        atomic_write(self.manager.run_dir / f"artifacts/model-{state.iteration:06d}.txt", response.text[:32768])
        self.manager.save(state)
        if response.input_tokens > config.max_context_tokens or response.output_tokens > config.max_new_tokens:
            self.stop(state, "Backend exceeded configured token allowance", failed=True)
            return None
        self.events.emit("llm_finished", iteration=state.iteration, tokens=actual)
        return response

    def validate_plan(self, action: PlanAction, state: AgentState) -> GateResult:
        proposed_reads = set(state.verified_reads)
        last_write = -1
        verification_steps = {}
        for index, step in enumerate(action.steps):
            arguments = step.arguments
            if step.tool == "write_file":
                if set(arguments) != {"path"}:
                    return blocked("Plan write_file with path only; generate content during execution")
                arguments = {**arguments, "content": ""}
                last_write = index
            proposal = ToolAction(type="tool", tool=step.tool, arguments=arguments)
            decision = self.executor.authorize(proposal, state)
            if not decision.allowed:
                return decision
            tool = self.executor.registry.get(step.tool)
            assert tool is not None
            # Canonical defaults make omitted path='.' equal to explicit path='.'.
            validated = tool.args_model.model_validate(arguments).model_dump()
            step.arguments = {"path": validated["path"]} if step.tool == "write_file" else validated
            if step.tool == "read_file":
                proposed_reads.add(str(Path(step.arguments["path"])))
            elif step.tool == "shell":
                verification_steps[step.arguments["command"]] = index
        if not proposed_reads or not set(state.required_reads).issubset(proposed_reads):
            return blocked("Plan must include read_file and all REQUIRED READS")
        for command in state.policy.required_verifications:
            if verification_steps.get(command, -1) <= last_write:
                return blocked(f"Plan must verify after all writes using command: {command}")
        return GateResult(allowed=True)

    def execute_tool(self, action: ToolAction, state: AgentState) -> None:
        decision = self.executor.authorize(action, state)
        if not decision.allowed:
            self.stop(state, decision.reason or "Execution denied")
            return
        state.tool_calls += 1
        state.pending_action = action
        self.manager.save(state)
        self.finish_pending_tool(state)

    def finish_pending_tool(self, state: AgentState) -> None:
        action = state.pending_action
        assert action is not None
        self.events.emit("tool_started", iteration=state.iteration, tool=action.tool)
        result = self.executor.execute_authorized(action)
        observation = self.observations.record(state.iteration, action, result)
        self.apply_observation(state, observation)
        self.events.emit("tool_finished", iteration=state.iteration, success=result.success)

    def recover_tool(self, state: AgentState) -> None:
        recent = self.observations.recent(1)
        if recent and recent[0].iteration == state.iteration:
            self.apply_observation(state, recent[0])
        else:
            # Only the built-in, idempotent read tools may be replayed in this slice.
            if time.time() - state.started_at >= state.limits.max_runtime_seconds:
                self.stop(state, "Runtime deadline reached before read recovery")
                return
            if state.pending_action.tool not in {"read_file", "list_files"}:
                self.stop(state, "Interrupted non-read tool requires explicit recovery")
                return
            from miniagent.gates.pipeline import ArgumentGate, PathGate, SchemaGate, ToolGate
            gates = GatePipeline([SchemaGate(), ToolGate(self.executor.registry),
                                  ArgumentGate(self.executor.registry), PathGate(self.executor.context)])
            decision = gates.check(state.pending_action, state)
            if not decision.allowed:
                self.stop(state, decision.reason or "Resume denied")
                return
            self.finish_pending_tool(state)
        self.events.emit("tool_recovered", iteration=state.iteration)

    def apply_observation(self, state: AgentState, observation: Observation) -> None:
        action = state.pending_action
        assert action is not None
        if observation.tool != action.tool or observation.arguments != action.arguments:
            raise ValueError("Pending action and observation disagree")
        current_signature = signature(action)
        repeated = state.last_action == current_signature and state.last_result_hash == observation.result_hash
        state.repeated_action_count = state.repeated_action_count + 1 if repeated else 1
        state.last_action = current_signature
        state.last_result_hash = observation.result_hash
        if observation.success:
            state.needs_replan = False
            state.metrics.successful_tools += 1
            state.consecutive_failures = 0
            step = state.current_step
            if step is not None:
                step.observation_id = observation.id
            if action.tool == "read_file":
                path = str(Path(action.arguments["path"]))
                if path not in state.verified_reads:
                    state.verified_reads.append(path)
                if path in state.required_reads[:4]:
                    state.required_read_summaries[path] = observation.summary[:1200]
            elif action.tool == "write_file":
                state.verifications = {}
                path = str(Path(action.arguments["path"]))
                state.verified_reads = [p for p in state.verified_reads if p != path]
                state.required_read_summaries.pop(path, None)
            elif action.tool == "shell" and observation.exit_code == 0 and observation.verification_digest:
                state.verifications[action.arguments["command"]] = observation.verification_digest
                state.repair_feedback = None
                state.last_failed_verification = None
                state.stalled_verifications = 0
            state.feedback = None
        else:
            state.needs_replan = True
            state.metrics.failed_tools += 1
            state.consecutive_failures += 1
            state.feedback = observation.summary
            state.repair_feedback = observation.summary
            if action.tool == "shell":
                state.verifications.pop(action.arguments["command"], None)
                try:
                    fingerprint = workspace_digest(self.executor.context) + observation.result_hash
                except (ValueError, OSError, RuntimeError):
                    fingerprint = observation.result_hash
                state.stalled_verifications = state.stalled_verifications + 1 if fingerprint == state.last_failed_verification else 1
                state.last_failed_verification = fingerprint
                if state.stalled_verifications >= state.options.fresh_after:
                    self.events.emit("repair_stalled", iteration=state.iteration, count=state.stalled_verifications)
        state.pending_action = None
        if action.tool == "shell":
            try:
                if keep_checkpoint(state, observation, self.manager.run_dir, self.executor.context):
                    self.events.emit("checkpoint_saved", iteration=state.iteration, passed=state.best_attempt.passed)
            except (OSError, ValueError, RuntimeError) as error:
                self.events.emit("checkpoint_unavailable", reason=str(error)[:400])
        self.manager.save(state)
