import re
from pathlib import Path

from miniagent.parsing.json_parser import ParseError
from miniagent.state.models import ToolAction


FENCE = re.compile(r"^(`{3,}|~{3,})([^\r\n]*)\r?$", re.MULTILINE)


def file_blocks(text: str) -> list[tuple[str, str]]:
    """Read outer fences, preserving nested shorter fences verbatim."""
    if len(text) > 32768:
        raise ParseError("File response exceeds 32768 characters")
    blocks = []
    position = 0
    while opening := FENCE.search(text, position):
        marker, language = opening.groups()
        # A longer outer fence preserves shorter fences inside Markdown files.
        closing = re.compile(r"^" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}[ \t]*\r?$", re.MULTILINE)
        end = closing.search(text, opening.end() + 1)
        if end is None:
            raise ParseError("Return the complete file in one closed fence; use a longer outer fence for nested code blocks")
        blocks.append((language.strip().lower(), text[opening.end() + 1:end.start()]))
        position = end.end()
    return blocks


def parse_file_content(text: str, path: str) -> ToolAction:
    """Extract a text file of any type, bound to the runtime's planned path."""
    blocks = file_blocks(text)
    if len(blocks) > 1:
        suffix = Path(path).suffix.lower().lstrip(".")
        aliases = {"py": {"python"}, "md": {"markdown"}, "js": {"javascript"}, "ts": {"typescript"},
                   "yml": {"yaml"}, "txt": {"text", "plaintext"}, "sh": {"bash", "shell"}}
        languages = {suffix} | aliases.get(suffix, set()) if suffix else set()
        blocks = [block for block in blocks if block[0] in languages]
    if len(blocks) != 1:
        raise ParseError("Return exactly one unambiguous closed code block for the planned file")
    content = blocks[0][1]
    if not content.strip():
        raise ParseError("The file content is empty")
    return ToolAction(type="tool", tool="write_file", arguments={"path": path, "content": content})
