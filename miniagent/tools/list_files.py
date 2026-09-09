import os

from pydantic import Field

from miniagent.state.models import StrictModel, ToolResult
from miniagent.tools.base import ToolContext, workspace_path


class ListFilesArgs(StrictModel):
    path: str = Field(default=".", min_length=1, max_length=1024)


class ListFiles:
    name = "list_files"
    description = "List one directory without recursion. Arguments: path (string, default '.')."
    args_model = ListFilesArgs

    def execute(self, args: ListFilesArgs, context: ToolContext) -> ToolResult:
        path = workspace_path(context.workspace, args.path)
        entries: list[str] = []
        size = 0
        truncated = False
        with os.scandir(path) as iterator:
            for entry in iterator:
                name = entry.name + ("/" if entry.is_dir(follow_symlinks=False) else "")
                if size + len(name) + 1 > context.output_limit:
                    truncated = True
                    break
                entries.append(name)
                size += len(name) + 1
        return ToolResult(
            success=True,
            output="\n".join(sorted(entries)),
            metadata={"truncated": truncated},
        )
