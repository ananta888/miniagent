import hashlib
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Protocol

from pydantic import BaseModel

from miniagent.state.models import ToolPolicy, ToolResult


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
    policy: ToolPolicy = field(default_factory=ToolPolicy)
    deadline: float | None = None


def writable_path(context: ToolContext, value: str) -> Path:
    path = workspace_path(context.workspace, value)
    if str(Path(value)) not in {str(Path(p)) for p in context.policy.write_paths}:
        raise ValueError("File is not in the configured write allowlist")
    current = context.workspace.resolve()
    for part in Path(value).parts:
        current /= part
        if current.is_symlink():
            raise ValueError("Writing through symlinks is forbidden")
    return path


def workspace_digest(context: ToolContext) -> str:
    """Bind verification to the exact bytes of the writable source files."""
    digest = hashlib.sha256()
    for name in sorted(set(context.policy.write_paths)):
        path = writable_path(context, name)
        digest.update(name.encode() + b"\x00")
        if not path.exists():
            digest.update(b"missing\x00")
            continue
        if not path.is_file() or path.stat().st_size > 32768:
            raise ValueError("Verification source must be a regular file of at most 32 KiB")
        with path.open("rb") as stream:
            data = stream.read(32769)
        if len(data) > 32768:
            raise ValueError("Verification source exceeds 32 KiB")
        digest.update(hashlib.sha256(data).digest())
    return digest.hexdigest()


class Tool(Protocol):
    name: str
    description: str
    args_model: type[BaseModel]

    def execute(self, args: BaseModel, context: ToolContext) -> ToolResult: ...
