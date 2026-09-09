import re
from pathlib import Path

from miniagent.parsing.json_parser import ParseError
from miniagent.state.models import ToolAction


def parse_file_content(text: str, path: str) -> ToolAction:
    """Bind an unambiguous fenced artifact to a planned path; never infer a tool/path."""
    if len(text) > 32768:
        raise ParseError("File response exceeds 32768 characters")
    fences = list(re.finditer(r"^```[^\n]*$", text, re.MULTILINE))
    if not fences or len(fences) % 2 or any(f.group().strip() != "```" for f in fences[1::2]):
        raise ParseError("Return the complete file in exactly one closed code fence")
    blocks = [(start.group()[3:].strip().lower(), text[start.end() + 1:end.start()])
              for start, end in zip(fences[::2], fences[1::2])]
    if len(blocks) > 1:
        languages = {".py": {"py", "python"}, ".json": {"json"}, ".txt": {"text", "txt", "plaintext"}}
        blocks = [block for block in blocks if block[0] in languages.get(Path(path).suffix, set())]
    if len(blocks) != 1:
        raise ParseError("Multiple possible files: return exactly one code block for the planned file")
    content = blocks[0][1]
    if not content.strip():
        raise ParseError("The file content is empty")
    return ToolAction(type="tool", tool="write_file", arguments={"path": path, "content": content})
