from miniagent.state.models import AgentState, PlanAction, StepState


class Planner:
    """Initial planning only. The runtime validates proposals before applying them."""

    def apply(self, action: PlanAction, state: AgentState) -> None:
        if state.steps:
            raise ValueError("Replanning is outside this first slice")
        state.steps = [StepState(proposal=step) for step in action.steps]

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
        return "\n".join(lines) + "\n"
