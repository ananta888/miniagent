import json
import textwrap

from pydantic import Field, ValidationError

from miniagent.parsing.file_parser import parse_file_content
from miniagent.parsing.json_parser import ParseError, reject_constant, unique_object
from miniagent.state.models import StrictModel, ToolAction


class LineEdit(StrictModel):
    line: int = Field(ge=1)
    replacement: str = Field(max_length=4000)


def parse_line_edit(text: str, path: str, source: str, expected_hash: str | None) -> ToolAction:
    if len(text) > 32768:
        raise ParseError("Edit response exceeds 32768 characters")
    if text.strip().startswith("```"):
        text = parse_file_content(text, path).arguments["content"]
    try:
        edit = LineEdit.model_validate(json.loads(text, object_pairs_hook=unique_object, parse_constant=reject_constant))
        lines = source.splitlines(keepends=True)
        if edit.line > len(lines):
            raise ValueError(f"line must be between 1 and {len(lines)}")
        original = lines[edit.line - 1]
        indent = original[:len(original) - len(original.lstrip(" \t"))]
        replacement = textwrap.indent(textwrap.dedent(edit.replacement).strip("\n") + "\n", indent) if edit.replacement else ""
        lines[edit.line - 1] = replacement
        content = "".join(lines)
        if content == source:
            raise ValueError("Edit does not change the file; choose a correction for the failing test")
        if path.endswith(".py"):
            compile(content, path, "exec")
    except (ValueError, ValidationError, SyntaxError, RecursionError) as error:
        raise ParseError(f"Invalid line edit: {str(error)[:400]}. Return JSON with line and replacement.") from error
    return ToolAction(type="tool", tool="write_file", arguments={
        "path": path, "content": content, "expected_hash": expected_hash,
    })
