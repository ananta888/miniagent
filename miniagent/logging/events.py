import time
from pathlib import Path
from typing import Any

from miniagent.state.files import append_json


class EventLog:
    def __init__(self, run_dir: Path):
        self.path = run_dir / "events.jsonl"

    def emit(self, event: str, **data: Any) -> None:
        append_json(self.path, {"event": event, "timestamp": time.time(), **data})
