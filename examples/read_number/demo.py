"""Deterministic runtime demonstration; this is not a language model benchmark."""

import json
from pathlib import Path

from miniagent.model.base import ModelResponse
from miniagent.runtime import Runtime
from miniagent.state.manager import StateManager
from miniagent.state.models import ModelConfig, RunLimits


class ScriptedBackend:
    def __init__(self):
        self.responses = iter([
            {"type": "plan", "steps": [
                {"description": "Inspect workspace", "tool": "list_files", "arguments": {"path": "."}},
                {"description": "Read the number", "tool": "read_file", "arguments": {"path": "example.txt"}},
            ]},
            {"type": "tool", "tool": "list_files", "arguments": {"path": "."}},
            {"type": "tool", "tool": "read_file", "arguments": {"path": "example.txt"}},
            {"type": "final", "answer": "example.txt contains 21. Twice that number is 42."},
        ])
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> ModelResponse:
        self.prompts.append(prompt)
        return ModelResponse(text=json.dumps(next(self.responses)), input_tokens=100, output_tokens=50)


def main() -> None:
    source = Path(__file__).parent / "workspace"
    manager = StateManager.create(
        Path("runs"), "Read example.txt and report twice the number in it.",
        ModelConfig(), RunLimits(), source, ["example.txt"],
    )
    model = ScriptedBackend()
    state = Runtime(manager, model).run()
    assert state.status == "completed", state.feedback
    assert len(model.prompts) == 4
    assert '"summary": "21\\n"' in model.prompts[-1]
    assert state.tool_calls == 2
    assert "42" in state.answer
    print(f"Run: {manager.run_dir}\n{state.status}: {state.answer}")


if __name__ == "__main__":
    main()
