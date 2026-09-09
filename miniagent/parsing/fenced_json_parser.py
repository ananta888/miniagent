import re

from miniagent.parsing.json_parser import StrictJSONParser
from miniagent.state.models import Action


def unwrap_fence(text: str) -> str | None:
    if len(text) > 32768:
        return None
    match = re.fullmatch(r"\s*```(?:json)?[ \t]*\r?\n(.*?)\r?\n```\s*", text, re.DOTALL)
    return match.group(1) if match else None


class FencedJSONParser:
    """Recover one Markdown wrapper; the contents must still be strict valid JSON."""

    def parse(self, text: str) -> Action | None:
        self.last_error = None
        body = unwrap_fence(text)
        if body is None:
            return None
        parser = StrictJSONParser()
        action = parser.parse(body)
        self.last_error = parser.last_error
        return action
