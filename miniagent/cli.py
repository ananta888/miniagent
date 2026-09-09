import argparse
import json
import sys
import time
import tomllib
from pathlib import Path

from miniagent.runtime import Runtime
from miniagent.state.manager import StateManager
from miniagent.state.models import ModelConfig, RunLimits, RuntimeOptions, ToolPolicy
from miniagent.logging.events import EventLog


def resolve_run(value: str, runs_dir: Path) -> Path:
    explicit = Path(value)
    if explicit.is_dir():
        return explicit
    if len(explicit.parts) != 1 or value in {".", ".."}:
        raise ValueError("Run must be an existing directory or a run ID")
    return runs_dir / value


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description="Minimal local agent runtime")
    commands = cli.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Create and execute a run")
    run.add_argument("goal")
    run.add_argument("--model", help="Local model path or Hugging Face model ID")
    run.add_argument("--config", type=Path, help="TOML with [model], [limits], [tools], [runtime]")
    run.add_argument("--workspace", type=Path, help="Directory copied into the new run")
    run.add_argument("--require-read", action="append", default=[], help="File that must be read completely")
    run.add_argument("--allow-download", action="store_true", help="Allow model files to be downloaded")
    run.add_argument("--runs-dir", type=Path, default=Path("runs"))
    for command in ("resume", "status"):
        sub = commands.add_parser(command)
        sub.add_argument("run")
        sub.add_argument("--runs-dir", type=Path, default=Path("runs"))
        if command == "resume":
            sub.add_argument("--config", type=Path, help="Explicitly update [limits], [runtime], or [model] for resume")
            sub.add_argument("--retry-blocked", action="store_true", help="Retry a blocked run with the saved goal and evidence")
    return cli


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "run":
            config = tomllib.loads(args.config.read_text()) if args.config else {}
            if set(config) - {"model", "limits", "tools", "runtime"}:
                raise ValueError("Config only accepts [model], [limits], [tools] and [runtime]")
            model_values = config.get("model", {})
            if args.model:
                model_values["model"] = args.model
            if args.allow_download:
                model_values["local_files_only"] = False
            manager = StateManager.create(
                args.runs_dir, args.goal, ModelConfig.model_validate(model_values),
                RunLimits.model_validate(config.get("limits", {})), args.workspace, args.require_read,
                ToolPolicy.model_validate(config.get("tools", {})),
                RuntimeOptions.model_validate(config.get("runtime", {})),
            )
            print(f"Run: {manager.run_dir}", flush=True)
        else:
            manager = StateManager(resolve_run(args.run, args.runs_dir))
            if args.command == "resume" and (args.config or args.retry_blocked):
                with manager.lock():
                    state = manager.recover()
                    values = tomllib.loads(args.config.read_text()) if args.config else {}
                    if set(values) - {"limits", "runtime", "model"}:
                        raise ValueError("Resume config only accepts [limits], [runtime] and [model]")
                    before = {"limits": state.limits.model_dump(), "runtime": state.options.model_dump(),
                              "model": state.model_config_saved.model_dump()}
                    state.limits = RunLimits.model_validate({**before["limits"], **values.get("limits", {})})
                    state.options = RuntimeOptions.model_validate({**before["runtime"], **values.get("runtime", {})})
                    if values.get("runtime", {}).get("prompt_artifact"):
                        manager.install_prompt(state, Path(values["runtime"]["prompt_artifact"]))
                    state.model_config_saved = ModelConfig.model_validate({**before["model"], **values.get("model", {})})
                    if args.retry_blocked and state.status == "blocked":
                        state.status = "running"
                        state.finished_at = None
                        state.parse_failures = 0
                        state.consecutive_blocks = 0
                    manager.save(state)
                    EventLog(manager.run_dir).emit("resume_configured", previous=before, config=values,
                                                  retry_blocked=args.retry_blocked)
        if args.command == "status":
            state = manager.load()
        else:
            state = Runtime(manager).run()
        print(json.dumps({
            "run_id": state.run_id, "status": state.status, "iterations": state.iteration,
            "tool_calls": state.tool_calls, "tokens": state.token_budget_used,
            "runtime_seconds": round((state.finished_at or time.time()) - state.started_at, 2),
            "metrics": state.metrics.model_dump(), "answer": state.answer, "reason": state.feedback,
        }, indent=2, ensure_ascii=False))
        return 0 if args.command == "status" or state.status == "completed" else 1
    except KeyboardInterrupt:
        print("Interrupted. Resume the printed run directory.", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, ImportError) as error:
        print(f"miniagent: {error}", file=sys.stderr)
        return 2
