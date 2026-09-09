import hashlib
from pathlib import Path

from miniagent.state.files import append_json, atomic_write, recent_json
from miniagent.state.models import Observation, ToolAction, ToolResult


class ObservationStore:
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.path = run_dir / "observations.jsonl"

    def record(self, iteration: int, action: ToolAction, result: ToolResult) -> Observation:
        reference = f"artifacts/tool-{iteration:06d}.json"
        raw = result.model_dump_json()
        atomic_write(self.run_dir / reference, raw + "\n")
        # Truncated output is useful context but insufficient evidence to finish a step.
        complete = result.success and not result.metadata.get("truncated", False)
        summary = result.output[:1200] if result.success else ((result.error or "Tool failed") + "\n" + result.output[-1100:])
        if not complete and result.success:
            summary += "\n[TRUNCATED: cannot verify this step]"
        observation = Observation(
            id=f"obs-{iteration:06d}", iteration=iteration,
            tool=action.tool, arguments=action.arguments,
            success=complete, summary=summary, raw_output_ref=reference,
            result_hash=hashlib.sha256(raw.encode()).hexdigest(),
            exit_code=result.exit_code,
            verification_digest=result.metadata.get("verification_digest"),
        )
        append_json(self.path, observation.model_dump())
        return observation

    def recent(self, count: int = 4) -> list[Observation]:
        return [Observation.model_validate(value) for value in recent_json(self.path, count)]
