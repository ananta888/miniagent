import fcntl
import hashlib
import shutil
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from miniagent.logging.events import EventLog
from miniagent.planning.planner import Planner
from miniagent.state.files import atomic_write, repair_tail
from miniagent.state.models import AgentState, ModelConfig, RunLimits, RuntimeOptions, ToolPolicy
from miniagent.tools.base import workspace_path


class StateManager:
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir.resolve()

    @classmethod
    def create(cls, runs_dir: Path, goal: str, model: ModelConfig, limits: RunLimits,
               source: Path | None = None, required_reads: list[str] | None = None,
               policy: ToolPolicy | None = None, options: RuntimeOptions | None = None) -> "StateManager":
        run_id = uuid.uuid4().hex[:12]
        state = AgentState(run_id=run_id, goal=goal, started_at=time.time(),
                           model_config_saved=model, limits=limits, policy=policy or ToolPolicy(),
                           options=options.model_copy(deep=True) if options else RuntimeOptions())
        run_dir = runs_dir.resolve() / run_id
        if source is not None and runs_dir.resolve().is_relative_to(source.resolve()):
            raise ValueError("Runs directory must be outside the source workspace")
        for path in [*(required_reads or []), *state.policy.write_paths]:
            workspace_path(run_dir / "workspace", path)
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "artifacts").mkdir()
        if source is None:
            (run_dir / "workspace").mkdir()
        else:
            shutil.copytree(source, run_dir / "workspace", symlinks=True)
        state.required_reads = [str(Path(path)) for path in required_reads or []]
        manager = cls(run_dir)
        if state.options.prompt_artifact:
            manager.install_prompt(state, Path(state.options.prompt_artifact))
        atomic_write(run_dir / "goal.md", f"# Goal\n\n{goal}\n")
        for name in ("observations.jsonl", "events.jsonl"):
            (run_dir / name).touch()
        manager.save(state)
        EventLog(run_dir).emit("run_started", run_id=run_id)
        return manager

    def install_prompt(self, state: AgentState, path: Path) -> None:
        from miniagent.prompts.strategy import PromptArtifact
        text = PromptArtifact.load(path).model_dump_json(indent=2)
        digest = hashlib.sha256(text.encode()).hexdigest()[:16]
        reference = f"artifacts/prompt-{digest}.json"
        atomic_write(self.run_dir / reference, text + "\n")
        state.options.prompt_artifact = reference

    @contextmanager
    def lock(self):
        with (self.run_dir / ".lock").open("a") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError("Run is already active in another process") from error
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def load(self) -> AgentState:
        state = AgentState.model_validate_json((self.run_dir / "state.json").read_text())
        if (self.run_dir / "goal.md").read_text() != f"# Goal\n\n{state.goal}\n":
            raise ValueError("goal.md differs from state.json; implicit goal changes are forbidden")
        return state

    def recover(self) -> AgentState:
        """Call under lock. JSON is authoritative; Markdown is a derived projection."""
        state = self.load()
        for name in ("observations.jsonl", "events.jsonl"):
            repair_tail(self.run_dir / name)
        atomic_write(self.run_dir / "plan.md", Planner().render(state))
        return state

    def save(self, state: AgentState) -> None:
        atomic_write(self.run_dir / "state.json", state.model_dump_json(indent=2) + "\n")
        atomic_write(self.run_dir / "plan.md", Planner().render(state))
