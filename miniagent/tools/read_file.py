import os
import stat

from pydantic import Field

from miniagent.state.models import StrictModel, ToolResult
from miniagent.tools.base import ToolContext, workspace_path


class ReadFileArgs(StrictModel):
    path: str = Field(min_length=1, max_length=1024)


class ReadFile:
    name = "read_file"
    description = "Read a bounded UTF-8 text file inside the workspace. Arguments: path (string)."
    args_model = ReadFileArgs

    def execute(self, args: ReadFileArgs, context: ToolContext) -> ToolResult:
        path = workspace_path(context.workspace, args.path)
        # O_NONBLOCK prevents hanging on a named pipe before checking its type.
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("Only regular files can be read")
            data = stream.read(context.output_limit + 1)
        truncated = len(data) > context.output_limit
        return ToolResult(
            success=True,
            output=data[:context.output_limit].decode("utf-8", errors="replace"),
            metadata={"truncated": truncated},
        )
