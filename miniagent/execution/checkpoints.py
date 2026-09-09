"""Keep the best observed candidate as repair context; completion still uses gates."""

import json
from pathlib import Path

from miniagent.state.files import atomic_write
from miniagent.state.models import AgentState, Checkpoint, Observation
from miniagent.tools.base import ToolContext, writable_path


def keep_checkpoint(state: AgentState, observation: Observation, root: Path, context: ToolContext) -> bool:
    if not state.options.keep_best or len(state.policy.required_verifications) != 1:
        return False
    if observation.arguments.get("command") != state.policy.required_verifications[0]:
        return False
    artifact = json.loads((root / observation.raw_output_ref).read_text())
    summary = None
    for line in artifact["output"].splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and isinstance(value.get("miniagent_verification"), dict):
            summary = value["miniagent_verification"]
    if summary is None:
        return False
    if any(type(summary.get(key)) is not int or summary[key] < 0
           for key in ("tests_passed", "failures", "errors", "tests_run")):
        return False
    passed, failures = summary["tests_passed"], summary["failures"] + summary["errors"]
    if passed > summary["tests_run"]:
        return False
    best = state.best_attempt
    if best and (passed, -failures) <= (best.passed, -best.failures):
        return False
    files = {}
    for index, name in enumerate(state.policy.write_paths):
        path = writable_path(context, name)
        if not path.is_file() or path.stat().st_size > 32768:
            continue
        reference = f"artifacts/checkpoint-{observation.id}-{index}.txt"
        with path.open("r", encoding="utf-8", newline="") as stream:
            source = stream.read(32769)
        if len(source.encode("utf-8")) > 32768:
            continue
        atomic_write(root / reference, source)
        files[name] = reference
    state.best_attempt = Checkpoint(passed=passed, failures=failures, files=files, feedback=observation.summary)
    return True
