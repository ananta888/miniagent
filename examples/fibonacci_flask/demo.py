"""Coding exercise: real local model by default, explicit scripted regression mode."""

import argparse
import json
from pathlib import Path
import sys
import tomllib

from miniagent.model.base import ModelResponse
from miniagent.runtime import Runtime
from miniagent.state.manager import StateManager
from miniagent.state.models import ModelConfig, RunLimits, ToolPolicy

HERE = Path(__file__).resolve().parent
GOAL = "Create the Fibonacci Flask backend described in SPEC.md in app.py and requirements.txt. Run verify and fix any failing tests before finishing."


def step(tool, arguments, description):
    return {"tool": tool, "arguments": arguments, "description": description}


def tool_action(tool, **arguments):
    return {"type": "tool", "tool": tool, "arguments": arguments}


class ScriptedCodingBackend:
    """Deliberately inject a wrong result, then repair it after real test failures."""

    def __init__(self):
        source = (HERE / "reference_app.py").read_text()
        incorrect = source.replace("value=a)", "value=a + 1)")
        self.responses = iter([
            {"type": "plan", "steps": [
                step("read_file", {"path": "SPEC.md"}, "Read API contract"),
                step("write_file", {"path": "app.py"}, "Implement API"),
                step("write_file", {"path": "requirements.txt"}, "Declare Flask dependency"),
                step("shell", {"command": "verify"}, "Verify API contract"),
            ]},
            tool_action("read_file", path="SPEC.md"),
            tool_action("write_file", path="app.py", content=incorrect),
            tool_action("write_file", path="requirements.txt", content="Flask>=3.1,<4\n"),
            tool_action("shell", command="verify"),
            {"type": "plan", "steps": [
                step("write_file", {"path": "app.py"}, "Fix Fibonacci off-by-one"),
                step("shell", {"command": "verify"}, "Verify corrected API"),
            ]},
            tool_action("write_file", path="app.py", content=source),
            tool_action("shell", command="verify"),
            {"type": "final", "answer": "Created app.py and requirements.txt. All 12 API contract tests pass."},
        ])
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        text = json.dumps(next(self.responses))
        return ModelResponse(text=text, input_tokens=100, output_tokens=500)


def create_run(runs_dir: Path, config: ModelConfig, limits: RunLimits | None = None) -> StateManager:
    policy = ToolPolicy(
        write_paths=["app.py", "requirements.txt"],
        commands={"verify": [sys.executable, str(HERE / "verify.py")]},
        required_verifications=["verify"],
    )
    return StateManager.create(runs_dir, GOAL, config, limits or RunLimits(max_iterations=20, max_tokens=150000),
                               HERE / "workspace", ["SPEC.md"], policy)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--scripted", action="store_true", help="Use fixed responses with an injected bug; no LLM")
    cli.add_argument("--model", default="microsoft/Phi-3.5-mini-instruct")
    cli.add_argument("--revision", default="main", help="Pin a model commit for reproducible comparisons")
    cli.add_argument("--allow-download", action="store_true")
    cli.add_argument("--runs-dir", type=Path, default=Path("runs"))
    cli.add_argument("--limits-config", type=Path, help="TOML file containing a [limits] table")
    args = cli.parse_args()
    config = ModelConfig(model=args.model, revision=args.revision, max_new_tokens=1536, max_context_tokens=8192,
                         local_files_only=not args.allow_download)
    limits = None
    if args.limits_config:
        values = tomllib.loads(args.limits_config.read_text())
        if set(values) != {"limits"}:
            cli.error("--limits-config requires exactly one [limits] table")
        limits = RunLimits.model_validate(values["limits"])
    manager = create_run(args.runs_dir, config, limits)
    print(f"Run: {manager.run_dir}", flush=True)
    backend = ScriptedCodingBackend() if args.scripted else None
    state = Runtime(manager, backend).run()
    print(json.dumps({"mode": "scripted regression" if args.scripted else "local model",
                      "status": state.status, "iterations": state.iteration, "tool_calls": state.tool_calls,
                      "replans": state.replans, "answer": state.answer, "reason": state.feedback}, indent=2))
    return 0 if state.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
