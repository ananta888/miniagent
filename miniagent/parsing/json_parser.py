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
    def __init__(self):
        self.last_error: str | None = None

    def parse(self, text: str) -> Action | None:
        self.last_error = None
        if len(text) > 32_768:
            self.last_error = "Response exceeds the 32768-character parser limit"
            return None
        try:
            data = json.loads(text, object_pairs_hook=unique_object, parse_constant=reject_constant)
            return ACTION_ADAPTER.validate_python(data)
        except json.JSONDecodeError as error:
            self.last_error = f"JSON error at line {error.lineno}, column {error.colno}: {error.msg}"
        except ValidationError as error:
            detail = error.errors(include_input=False)[0]
            self.last_error = f"Action schema error at {'.'.join(map(str, detail['loc']))}: {detail['msg']}"
        except (ValueError, RecursionError) as error:
            self.last_error = str(error)[:400]
        return None


class ParserPipeline:
    def __init__(self, parsers: list[ResponseParser]):
        self.parsers = parsers
        self.recovered = False

    def parse(self, text: str) -> Action:
        self.recovered = False
        detail = "Response does not match a supported action format"
        for index, parser in enumerate(self.parsers):
            action = parser.parse(text)
            if action is not None:
                self.recovered = index > 0
                return action
            if getattr(parser, "last_error", None):
                detail = parser.last_error
        raise ParseError(f"{detail}. Return exactly one JSON action with type 'plan', 'tool', or 'final'.")
