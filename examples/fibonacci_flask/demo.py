"""Coding exercise: real local model by default, explicit scripted regression mode."""

import argparse
import json
from pathlib import Path
import sys
import tomllib

from miniagent.model.base import ModelResponse
from miniagent.runtime import Runtime
from miniagent.state.manager import StateManager
from miniagent.state.models import ModelConfig, RunLimits, RuntimeOptions, ToolPolicy
from miniagent.state.files import atomic_write
from miniagent.logging.events import EventLog

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


def create_run(runs_dir: Path, config: ModelConfig, limits: RunLimits | None = None,
               options: RuntimeOptions | None = None, references: list[Path] | None = None,
               modular: bool = False) -> StateManager:
    options = options.model_copy(deep=True) if options else RuntimeOptions()
    if modular:
        options.file_tasks = {
            "logic.py": "Write the Python function fibonacci(n). Return F(n), with F(0)=0 and F(1)=1. Support n=1000 using linear time, without recursion. Return only the complete function in one python code fence.",
            "app.py": ("Write app.py with Flask instance app. Import fibonacci from logic; the calculation is already implemented. "
                       "GET /health returns JSON {\"status\":\"ok\"}. GET /fibonacci?n=10 returns JSON {\"n\":10,\"value\":55}. "
                       "Read n exactly once with request.args.getlist. Accept ASCII decimal digits and numeric values 0 through 1000. "
                       "Leading zeros are allowed, even 5000 zeros. Strip leading zeros before bounding the significant digits and converting to int. "
                       "Missing, empty, repeated, non-ASCII, negative, signed, fractional or out-of-range input returns JSON error with HTTP 400. "
                       "Call fibonacci(n) and return jsonify(n=n, value=result). Do not implement the calculation in this file. "
                       "Do not start a server during import. Return only the complete file in one python code fence."),
        }
    policy = ToolPolicy(
        write_paths=(["logic.py"] if modular else []) + ["app.py", "requirements.txt"],
        commands={"verify": [sys.executable, str(HERE / "verify.py")]},
        required_verifications=["verify"],
    )
    if len(references or []) > 3:
        raise ValueError("At most three reference files fit the pinned input context")
    reference_texts = [path.read_text() for path in references or []]
    if any(len(text) > 1200 for text in reference_texts):
        raise ValueError("Reference files must fit the 1200-character pinned input limit")
    manager = StateManager.create(runs_dir, GOAL, config, limits or RunLimits(
        max_iterations=150, max_tool_calls=120, max_tokens=1000000, max_consecutive_failures=10,
        max_blocked_actions=8, max_repeated_actions=5), HERE / "workspace", ["SPEC.md"], policy, options)
    state = manager.load()
    for index, text in enumerate(reference_texts):
        name = f"REFERENCE_{index}.md"
        atomic_write(manager.run_dir / "workspace" / name, text)
        state.required_reads.append(name)
        EventLog(manager.run_dir).emit("reference_added", path=name)
    manager.save(state)
    return manager


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--scripted", action="store_true", help="Use fixed responses with an injected bug; no LLM")
    cli.add_argument("--model", default="microsoft/Phi-3.5-mini-instruct")
    cli.add_argument("--revision", default="main", help="Pin a model commit for reproducible comparisons")
    cli.add_argument("--allow-download", action="store_true")
    cli.add_argument("--runs-dir", type=Path, default=Path("runs"))
    cli.add_argument("--limits-config", type=Path, help="TOML file containing a [limits] table")
    cli.add_argument("--file-output-format", choices=["json", "fenced"], default="fenced")
    cli.add_argument("--repair-strategy", choices=["model", "rewrite"], default="rewrite")
    cli.add_argument("--model-every-step", action="store_true", help="Ask the model even for fully specified plan steps")
    cli.add_argument("--reference", type=Path, action="append", default=[], help="Small explicit local API reference (max 1200 characters)")
    cli.add_argument("--model-planning", action="store_true", help="Have the model plan instead of deriving a plan from declared files")
    cli.add_argument("--temperature", type=float, default=0.0)
    cli.add_argument("--seed", type=int, default=0)
    cli.add_argument("--no-keep-best", action="store_true", help="Repair the last attempt instead of the best verified candidate")
    cli.add_argument("--repair-edit", choices=["file", "line"], default="file")
    cli.add_argument("--repair-path", action="append", help="Restrict repairs to selected output files (default: app.py)")
    cli.add_argument("--prompt-artifact", type=Path, help="Use a portable prompt exported by the DSPy optimizer")
    cli.add_argument("--modular", action="store_true", help="Separate function generation (logic.py) from the Flask HTTP layer")
    args = cli.parse_args()
    if args.scripted and args.modular:
        cli.error("--modular requires a real model; the scripted fixture generates one app.py")
    config = ModelConfig(model=args.model, revision=args.revision, max_new_tokens=1536, max_context_tokens=8192,
                         local_files_only=not args.allow_download, temperature=args.temperature, seed=args.seed)
    limits = None
    if args.limits_config:
        values = tomllib.loads(args.limits_config.read_text())
        if set(values) != {"limits"}:
            cli.error("--limits-config requires exactly one [limits] table")
        limits = RunLimits.model_validate(values["limits"])
    options = RuntimeOptions(file_output_format="json" if args.scripted else args.file_output_format,
                             repair_strategy="model" if args.scripted else args.repair_strategy,
                             execute_plan=not (args.scripted or args.model_every_step),
                             planning_strategy="model" if args.scripted or args.model_planning else "files",
                             keep_best=not (args.scripted or args.no_keep_best),
                             repair_edit="file" if args.scripted else args.repair_edit,
                             repair_paths=[] if args.scripted else (args.repair_path or ["app.py"]),
                             prompt_artifact=str(args.prompt_artifact) if args.prompt_artifact else None)
    manager = create_run(args.runs_dir, config, limits, options, args.reference, args.modular)
    print(f"Run: {manager.run_dir}", flush=True)
    backend = ScriptedCodingBackend() if args.scripted else None
    state = Runtime(manager, backend).run()
    print(json.dumps({"mode": "scripted regression" if args.scripted else "local model",
                      "status": state.status, "iterations": state.iteration, "tool_calls": state.tool_calls,
                      "replans": state.replans, "answer": state.answer, "reason": state.feedback}, indent=2))
    return 0 if state.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
