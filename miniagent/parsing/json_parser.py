import json
from typing import Protocol

from pydantic import ValidationError

from miniagent.state.models import ACTION_ADAPTER, Action


class ParseError(ValueError):
    pass


class ResponseParser(Protocol):
    def parse(self, text: str) -> Action | None: ...


def unique_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


class StrictJSONParser:
    def parse(self, text: str) -> Action | None:
        if len(text) > 32_768:
            return None
        try:
            data = json.loads(text, object_pairs_hook=unique_object, parse_constant=reject_constant)
            return ACTION_ADAPTER.validate_python(data)
        except (ValueError, ValidationError, RecursionError):
            return None


class ParserPipeline:
    def __init__(self, parsers: list[ResponseParser]):
        self.parsers = parsers

    def parse(self, text: str) -> Action:
        for parser in self.parsers:
            action = parser.parse(text)
            if action is not None:
                return action
        raise ParseError("Return exactly one JSON action with type 'plan', 'tool', or 'final'.")
