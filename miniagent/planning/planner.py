from miniagent.state.models import AgentState, PlanAction, PlanStep, StepState


class Planner:
    """Apply validated plans, retaining evidence from completed steps on replan."""

    def initial(self, state: AgentState) -> PlanAction:
        steps = [PlanStep(description=f"Read {path}", tool="read_file", arguments={"path": path})
                 for path in state.required_reads]
        steps += [PlanStep(description=f"Create {path}", tool="write_file", arguments={"path": path})
                  for path in state.policy.write_paths]
        steps += [PlanStep(description=f"Verify with {command}", tool="shell", arguments={"command": command})
                  for command in state.policy.required_verifications]
        return PlanAction(type="plan", steps=steps)

    def repair(self, state: AgentState) -> PlanAction:
        """Explicit opt-in policy: rewrite permitted artifacts, then verify again."""
        steps = [PlanStep(description=f"Correct {path} using observed errors", tool="write_file",
                          arguments={"path": path}) for path in state.options.repair_paths or state.policy.write_paths]
        steps += [PlanStep(description=f"Verify with {command}", tool="shell", arguments={"command": command})
                  for command in state.policy.required_verifications]
        return PlanAction(type="plan", steps=steps)

    def apply(self, action: PlanAction, state: AgentState) -> None:
        if state.steps:
            state.replans += 1
        # Older evidence remains in observations.jsonl and the explicit evidence fields.
        completed = [step for step in state.steps if step.observation_id is not None][-12:]
        state.steps = completed + [StepState(proposal=step) for step in action.steps]
        state.needs_replan = False

    def render(self, state: AgentState) -> str:
        lines = ["# Goal", "", state.goal, "", "# Plan", ""]
        for step in state.steps:
            mark = "x" if step.observation_id else " "
            lines.append(f"- [{mark}] {step.proposal.description}")
        if not state.steps:
            lines.append("Initial planning pending.")
        current = state.current_step
        lines += ["", "# Current Step", "", current.proposal.description if current else "None."]
        evidence = [f"- {step.observation_id}: {step.proposal.description}" for step in state.steps if step.observation_id]
        lines += ["", "# Findings", "", *(evidence or ["None."])]
        lines += ["", "# Blockers", "", state.feedback or "None."]
        lines += ["", "# Completion Criteria", "",
                  "- Every planned tool action has a complete successful observation.",
                  "- At least one file has been read completely."]
        lines += [f"- Read `{path}` completely." for path in state.required_reads]
        lines += [f"- Command `{name}` succeeds against the current source bytes."
                  for name in state.policy.required_verifications]
        return "\n".join(lines) + "\n"
