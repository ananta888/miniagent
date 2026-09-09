import json

from miniagent.parsing.fenced_json_parser import unwrap_fence
from miniagent.parsing.json_parser import StrictJSONParser, reject_constant, unique_object
from miniagent.state.models import Action


class ToolRecoveryParser:
    """A plan label with exactly a tool-call body is a proposal, never permission."""

    def parse(self, text: str) -> Action | None:
        if len(text) > 32768:
            return None
        try:
            data = json.loads(unwrap_fence(text) or text, object_pairs_hook=unique_object,
                              parse_constant=reject_constant)
        except (ValueError, RecursionError):
            return None
        if (not isinstance(data, dict) or set(data) != {"type", "tool", "arguments"}
                or data["type"] != "plan"):
            return None
        data["type"] = "tool"
        return StrictJSONParser().parse(json.dumps(data))
