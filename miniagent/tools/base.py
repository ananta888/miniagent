from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Protocol

from pydantic import BaseModel

from miniagent.state.models import ToolResult


def workspace_path(root: Path, value: str) -> Path:
    """Use the same policy in the gate and immediately before file access."""
    path = Path(value)
    if not value or "\x00" in value:
        raise ValueError("Path must be nonempty and contain no NUL")
    if path.is_absolute() or PureWindowsPath(value).drive or "\\" in value:
        raise ValueError("Only relative POSIX workspace paths are allowed")
    if ".." in path.parts:
        raise ValueError("Parent traversal is forbidden")
    root = root.resolve()
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("Path escapes the workspace")
    return resolved


@dataclass(frozen=True)
class ToolContext:
    workspace: Path
    output_limit: int = 8192


class Tool(Protocol):
    name: str
    description: str
    args_model: type[BaseModel]

    def execute(self, args: BaseModel, context: ToolContext) -> ToolResult: ...
