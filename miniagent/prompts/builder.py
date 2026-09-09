import json
from importlib.resources import files

from miniagent.state.models import AgentState
from miniagent.tools.registry import ToolRegistry


class PromptBuilder:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def build(self, state: AgentState, context: dict) -> str:
        prompts = files("miniagent.prompts")
        mode = "executor.md" if state.steps else "planner.md"
        return "\n\n".join([
            prompts.joinpath("system.md").read_text(encoding="utf-8"),
            prompts.joinpath(mode).read_text(encoding="utf-8"),
            "AVAILABLE TOOLS\n" + json.dumps(self.registry.definitions()),
            json.dumps(context, ensure_ascii=True),
        ])
