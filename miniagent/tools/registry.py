from miniagent.tools.base import Tool


class ToolRegistry:
    def __init__(self, tools: list[Tool]):
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"Duplicate tool: {tool.name}")
            self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def definitions(self) -> list[dict]:
        return [
            {"name": t.name, "description": t.description, "arguments": t.args_model.model_json_schema()}
            for t in self._tools.values()
        ]
