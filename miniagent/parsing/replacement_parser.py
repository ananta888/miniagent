"""Exact, uniquely matching text edits for any UTF-8 file, with stale-write protection."""
from miniagent.parsing.file_parser import file_blocks
from miniagent.parsing.json_parser import ParseError
from miniagent.state.models import ToolAction


def parse_replacement(text: str, path: str, source: str, expected_hash: str | None) -> ToolAction:
    blocks = file_blocks(text)
    labels = [kind for kind, _ in blocks]
    if len(blocks) != 2 or not (labels == ['before', 'after'] or labels[0] == labels[1]):
        raise ParseError('Return two closed fences: before (exact existing text), then after (replacement).')
    before, after = [content for _, content in blocks]
    if not before.strip() or source.count(before) != 1:
        raise ParseError('The before block must match exactly one existing source fragment, including indentation.')
    if before == after:
        raise ParseError('Your before and after blocks are identical. Change the faulty code in after; copying it cannot fix the test.')
    content = source.replace(before, after, 1)
    if len(content) > 16000:
        raise ParseError('Replacement exceeds the file limit.')
    return ToolAction(type='tool', tool='write_file', arguments={
        'path': path, 'content': content, 'expected_hash': expected_hash,
    })
