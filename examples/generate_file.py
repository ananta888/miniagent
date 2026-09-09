"""Generate one UTF-8 file with an already running local llama-server."""
import argparse
import json
import sys
import tempfile
import tomllib
from pathlib import Path

from miniagent.model.local_llama import LocalLlamaBackend
from miniagent.runtime import Runtime
from miniagent.state.manager import StateManager
from miniagent.state.models import ModelConfig, RunLimits, RuntimeOptions, ToolPolicy


def create_run(runs_dir: Path, goal: str, output: str, model: ModelConfig,
               limits: RunLimits) -> StateManager:
    if Path(output) == Path('SPEC.md'):
        raise ValueError('SPEC.md is reserved for the immutable task input')
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory)
        (source / 'SPEC.md').write_text(goal, encoding='utf-8')
        return StateManager.create(
            runs_dir, goal, model, limits, source, ['SPEC.md'],
            ToolPolicy(write_paths=[output]),
            RuntimeOptions(planning_strategy='files', execute_plan=True,
                           repair_strategy='rewrite', repair_paths=[output]),
        )


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('goal', nargs='?')
    cli.add_argument('--output', help='Relative destination inside the new run workspace')
    cli.add_argument('--port', type=int, default=18089)
    cli.add_argument('--runs-dir', type=Path, default=Path('runs'))
    cli.add_argument('--resume', type=Path, help='Continue an interrupted run using its saved goal and output')
    cli.add_argument('--limits-config', type=Path, help='TOML containing [limits]')
    args = cli.parse_args(argv)
    if not 1 <= args.port <= 65535:
        cli.error('Invalid local port')
    if args.resume and (args.goal or args.output or args.limits_config):
        cli.error('--resume uses the saved goal, output and limits')
    if not args.resume and (not args.goal or not args.output):
        cli.error('Provide a goal and --output, or --resume RUN_DIRECTORY')
    try:
        manager = StateManager(args.resume) if args.resume else None
        saved = manager.load() if manager else None
        config = saved.model_config_saved if saved else ModelConfig(
            max_new_tokens=4096, max_context_tokens=4096,
            max_generation_seconds=180.0, temperature=0.4,
        )
        backend = LocalLlamaBackend(config, args.port)
        if not saved or saved.status == 'running':
            loaded = Path(backend.request('/props')['model_path']).resolve()
            if saved and loaded != Path(config.model).resolve():
                raise ValueError('The local server has loaded a different model')
            if not saved:
                config.model = str(loaded)
                config.revision = 'local-file'  # No unsupported upstream revision claim.
                values = tomllib.loads(args.limits_config.read_text()) if args.limits_config else {}
                if set(values) - {'limits'}:
                    raise ValueError('Limits config only accepts [limits]')
                limits = RunLimits.model_validate(values.get('limits', {}))
                manager = create_run(args.runs_dir, args.goal, args.output, config, limits)
        print(f'Run: {manager.run_dir}', flush=True)
        state = Runtime(manager, backend).run()
        print(json.dumps({'status': state.status, 'reason': state.feedback,
                          'files': [str(manager.run_dir / 'workspace' / p)
                                    for p in state.policy.write_paths]}, indent=2))
        print('Completion checks file creation, not application behavior. Test the generated file.')
        return 0 if state.status == 'completed' else 1
    except KeyboardInterrupt:
        print('Interrupted. Continue with --resume RUN_DIRECTORY.', file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError) as error:
        print(f'generate_file: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
