from pathlib import Path
from typing import Protocol

from pydantic import Field, model_validator

from miniagent.state.models import AgentState, StrictModel


class PromptStrategy(Protocol):
    def build(self, state: AgentState, context: dict) -> str: ...


class PromptArtifact(StrictModel):
    """Portable data only: no DSPy imports, executable modules or pickles."""
    version: int = Field(default=1, ge=1, le=1)
    instructions: str = Field(min_length=1, max_length=16000)
    input_fields: list[str] = Field(min_length=1, max_length=12)
    output_field: str
    demos: list[dict[str, str]] = Field(default_factory=list, max_length=16)
    file_suffixes: list[str] | None = Field(default_factory=lambda: [".py"], max_length=8)

    @model_validator(mode="after")
    def check_fields(self):
        names = [*self.input_fields, self.output_field]
        if len(set(names)) != len(names) or any(not name.isidentifier() for name in names):
            raise ValueError("Prompt fields must be distinct identifiers")
        if any(set(demo) != set(names) for demo in self.demos):
            raise ValueError("Each demonstration must contain exactly the declared input and output fields")
        if sum(len(value) for demo in self.demos for value in demo.values()) > 64000:
            raise ValueError("Demonstrations exceed the 64000-character allowance")
        if any(not suffix.startswith(".") or "/" in suffix or "\\" in suffix for suffix in self.file_suffixes or []):
            raise ValueError("File suffixes must be extensions such as .py")
        return self

    def render(self, inputs: dict[str, str]) -> str:
        sections = [self.instructions]
        for demo in self.demos:
            fields = [f"{name.upper()}\n{demo[name]}" for name in [*self.input_fields, self.output_field]]
            sections.append("EXAMPLE\n" + "\n\n".join(fields))
        sections.append("\n\n".join(f"{name.upper()}\n{inputs[name]}" for name in self.input_fields))
        return "\n\n".join(sections)

    @classmethod
    def load(cls, path: Path) -> "PromptArtifact":
        with path.open(encoding="utf-8") as stream:
            text = stream.read(100001)
        if len(text) > 100000:
            raise ValueError("Prompt artifact exceeds 100000 characters")
        return cls.model_validate_json(text)


class ArtifactPromptStrategy:
    def __init__(self, baseline: PromptStrategy, artifact: PromptArtifact):
        if artifact.input_fields != ["task"]:
            raise ValueError("Runtime prompt artifacts require exactly one input: task")
        self.baseline, self.artifact = baseline, artifact

    def build(self, state: AgentState, context: dict) -> str:
        task = self.baseline.build(state, context)
        if (state.current_step and state.current_step.proposal.tool == "write_file" and not state.needs_replan
                and (self.artifact.file_suffixes is None
                     or Path(state.current_step.proposal.arguments["path"]).suffix in self.artifact.file_suffixes)):
            return self.artifact.render({"task": task})
        return task
