from pydantic import Field

from miniagent.state.files import atomic_write
from miniagent.state.models import StrictModel, ToolResult
from miniagent.tools.base import ToolContext, writable_path


class WriteFileArgs(StrictModel):
    path: str = Field(min_length=1, max_length=1024)
    content: str = Field(max_length=16000)


class WriteFile:
    name = "write_file"
    description = "Atomically replace an allowed UTF-8 file. Arguments: path and content (strings)."
    args_model = WriteFileArgs

    def execute(self, args: WriteFileArgs, context: ToolContext) -> ToolResult:
        path = writable_path(context, args.path)
        data = args.content.encode("utf-8")
        if len(data) > 32768:
            raise ValueError("File content exceeds 32 KiB")
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(writable_path(context, args.path), args.content)
        return ToolResult(success=True, output=f"Wrote {len(data)} bytes to {args.path}")
