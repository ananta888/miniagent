from typing import Protocol

from pydantic import Field

from miniagent.state.models import StrictModel


class ModelResponse(StrictModel):
    text: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class ModelBackend(Protocol):
    def generate(self, prompt: str) -> ModelResponse: ...
