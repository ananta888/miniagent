import json
from importlib.resources import files

from miniagent.state.models import AgentState
from miniagent.tools.registry import ToolRegistry


class PromptBuilder:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def build(self, state: AgentState, context: dict) -> str:
        prompts = files("miniagent.prompts")
        planning = not state.steps or state.needs_replan
        mode = "planner.md" if planning else ("executor.md" if state.current_step else "final.md")
        definitions = self.registry.definitions()
        output_format = ""
        if planning:
            for definition in definitions:
                if definition["name"] == "write_file":
                    definition["description"] = "Plan a write to an allowed path; content is generated in a later execution step."
                    definition["arguments"] = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
        elif state.current_step:
            step = state.current_step.proposal
            definitions = [d for d in definitions if d["name"] == step.tool]
            arguments = dict(step.arguments)
            if step.tool == "write_file":
                output_format = (
                    "REQUIRED OUTPUT\nWrite the actual file now. Return a JSON object with type set to tool "
                    "and tool set to write_file. Its arguments object must contain path set to "
                    + json.dumps(arguments["path"])
                    + " and content set to the complete file text you generate for CURRENT GOAL. "
                    "Generate working source code, not a placeholder, template, or description."
                )
            else:
                output_format = "REQUIRED OUTPUT FORMAT\n" + json.dumps({"type": "tool", "tool": step.tool, "arguments": arguments})
        return "\n\n".join([
            prompts.joinpath("system.md").read_text(encoding="utf-8"),
            prompts.joinpath(mode).read_text(encoding="utf-8"),
            "AVAILABLE TOOLS\n" + json.dumps(definitions),
            json.dumps(context, ensure_ascii=True),
            output_format,
        ])
