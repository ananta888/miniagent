"""Generate and repair a Tetris engine and browser UI against an external contract."""
import argparse
import json
import shutil
from pathlib import Path

from miniagent.model.local_llama import LocalLlamaBackend
from miniagent.logging.events import EventLog
from miniagent.runtime import Runtime
from miniagent.state.manager import StateManager
from miniagent.state.models import ModelConfig, RunLimits, RuntimeOptions, ToolPolicy

ROOT = Path(__file__).resolve().parent
GOAL = ('Create a playable Tetris with engine.js and tetris.html following SPEC.md. '
        'Fix all failures reported by the trusted verify command. Keep both files compact.')


def configuration():
    node = shutil.which('node')
    if not node:
        raise ValueError('Node.js is required for the Tetris contract')
    spec = (ROOT / 'task/SPEC.md').read_text()
    policy = ToolPolicy(write_paths=['engine.js', 'tetris.html'],
                        commands={name: [node, str(ROOT / 'verify.mjs'), flag]
                                  for name, flag in [('engine', '--engine'), ('ui', '--ui')]},
                        required_verifications=['engine', 'ui'], command_timeout_seconds=10)
    engine_spec, ui_spec = spec.split('tetris.html loads', 1)
    ui_spec = ('tetris.html loads' + ui_spec + '\nTetris exposes board:20x10 numeric cells, '
               'piece:numeric matrix, x,y:piece position, score,gameOver. '
               'Methods:move(dx),rotate(),tick(),hardDrop(),reset(). Do not reimplement the engine.')
    options = RuntimeOptions(planning_strategy='files', execute_plan=True, repair_strategy='rewrite',
                             repair_edit='replace',
                             repair_paths=['engine.js', 'tetris.html'],
                             repair_by_command={'engine': ['engine.js'], 'ui': ['tetris.html']},
                             file_tasks={p: f'Write only {p}, complete in one closed code fence. '
                                         f'No JSON. Keep under 6000 characters.\n{task}'
                                         for p,task in [('engine.js',engine_spec),('tetris.html',ui_spec)]})
    limits = RunLimits(max_iterations=250, max_tool_calls=200, max_tokens=1000000,
                       max_runtime_seconds=1800, max_replans=40, max_parse_retries=8,
                       max_consecutive_failures=10, max_blocked_actions=8)
    return policy, options, limits


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--port',type=int,default=18089)
    cli.add_argument('--runs-dir',type=Path,default=Path('runs'))
    cli.add_argument('--resume',type=Path)
    cli.add_argument('--repair-edit',choices=['file','line','replace'])
    cli.add_argument('--max-replans',type=int)
    cli.add_argument('--retry-blocked',action='store_true')
    args=cli.parse_args()
    config=ModelConfig(max_new_tokens=4096,max_context_tokens=4096,temperature=0.4,
                       max_generation_seconds=180)
    backend=LocalLlamaBackend(config,args.port)
    if args.resume:
        manager=StateManager(args.resume)
        backend.config=manager.load().model_config_saved
    else:
        config.model=backend.request('/props')['model_path']
        config.revision='local-file'
        policy,options,limits=configuration()
        manager=StateManager.create(args.runs_dir,GOAL,config,limits,ROOT/'task',['SPEC.md'],policy,options)
    if Path(backend.request('/props')['model_path']).resolve()!=Path(backend.config.model).resolve():
        raise ValueError('Loaded model differs from saved run')
    if args.repair_edit or args.max_replans is not None or args.retry_blocked:
        with manager.lock():
            state=manager.load()
            before={'options':state.options.model_dump(),'limits':state.limits.model_dump()}
            if args.repair_edit:
                state.options.repair_edit=args.repair_edit
            if args.max_replans is not None:
                state.limits=RunLimits.model_validate({**state.limits.model_dump(),'max_replans':args.max_replans})
            if args.retry_blocked and state.status=='blocked':
                state.status='running'
                state.finished_at=None
                state.parse_failures=0
                state.consecutive_blocks=0
            manager.save(state)
            EventLog(manager.run_dir).emit('resume_configured',previous=before,
                                          repair_edit=args.repair_edit,max_replans=args.max_replans,
                                          retry_blocked=args.retry_blocked)
    print(f'Run: {manager.run_dir}',flush=True)
    state=Runtime(manager,backend).run()
    print(json.dumps({'status':state.status,'reason':state.feedback,'replans':state.replans,
                      'metrics':state.metrics.model_dump(),
                      'workspace':str(manager.run_dir/'workspace')},indent=2))
    return 0 if state.status=='completed' else 1


if __name__=='__main__':
    raise SystemExit(main())
