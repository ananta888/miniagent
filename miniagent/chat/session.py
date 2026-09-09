import fcntl
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import Field

from miniagent.state.files import atomic_write, repair_tail
from miniagent.state.models import ModelConfig, RunLimits, RuntimeOptions, StrictModel, ToolPolicy


class Message(StrictModel):
    role: str
    text: str
    timestamp: float = Field(default_factory=time.time)


class ChatState(StrictModel):
    model: ModelConfig = Field(default_factory=lambda: ModelConfig(
        max_context_tokens=4096, max_new_tokens=4096, temperature=0.4, max_generation_seconds=180))
    port: int = Field(default=18089, ge=1, le=65535)
    backend: Literal['llama', 'transformers'] = 'llama'
    model_bound: bool = False
    source: str | None = None
    latest_run: str | None = None
    policy: ToolPolicy = Field(default_factory=lambda: ToolPolicy(write_paths=['index.html']))
    limits: RunLimits = Field(default_factory=RunLimits)
    options: RuntimeOptions = Field(default_factory=lambda: RuntimeOptions(
        planning_strategy='files', execute_plan=True, repair_strategy='rewrite'))
    messages: list[Message] = Field(default_factory=list)


class ChatStore:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def lock(self):
        with (self.directory / '.lock').open('a') as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError('This chat session is already open') from error
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def load(self) -> ChatState:
        return ChatState.model_validate_json((self.directory / 'session.json').read_text())

    def recover(self) -> None:
        """Call under the session lock before starting the UI."""
        log = self.directory / 'chat.jsonl'
        if log.exists():
            repair_tail(log)

    def save(self, state: ChatState) -> None:
        atomic_write(self.directory / 'session.json', state.model_dump_json(indent=2) + '\n')

    def record(self, state: ChatState, role: str, text: str) -> None:
        message = Message(role=role, text=text[:16000])
        with (self.directory / 'chat.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(message.model_dump_json() + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        state.messages = [*state.messages[-39:], message]
        self.save(state)
