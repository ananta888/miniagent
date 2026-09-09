from miniagent.parsing.file_parser import file_blocks, parse_file_content
from miniagent.parsing.function_edit_parser import function_target, parse_function_edit
from miniagent.parsing.json_parser import ParseError, ParserPipeline
from miniagent.parsing.line_edit_parser import parse_line_edit
from miniagent.state.models import AgentState


class ActionParser:
    """Choose a response format from explicit state; execution remains outside parsing."""
    def __init__(self, pipeline: ParserPipeline):
        self.pipeline = pipeline
        self.recovered = False
        self.method = "json"

    def parse(self, text: str, state: AgentState, context: dict):
        self.recovered, self.method = False, "json"
        step = state.current_step
        if not (state.options.file_output_format == "fenced" and not state.needs_replan
                and step and step.proposal.tool == "write_file"):
            action = self.pipeline.parse(text)
            self.recovered = self.pipeline.recovered
            return action
        path = step.proposal.arguments["path"]
        target = function_target(state, context)
        if target:
            self.method = "function"
            return parse_function_edit(text, path, context["CURRENT FILE"], target, context["WORKSPACE FILE HASH"])
        if (state.options.repair_edit == "line" and state.repair_feedback and context.get("CURRENT FILE")
                and (not state.options.repair_paths or path in state.options.repair_paths)):
            self.method = "line"
            try:
                return parse_line_edit(text, path, context["CURRENT FILE"], context["WORKSPACE FILE HASH"])
            except ParseError as edit_error:
                try:
                    action = parse_file_content(text, path)
                    content = action.arguments["content"]
                    if content == context["CURRENT FILE"]:
                        raise ValueError("Unchanged file")
                    if path.endswith(".py"):
                        compile(content, path, "exec")
                    action.arguments["expected_hash"] = context["WORKSPACE FILE HASH"]
                    self.recovered, self.method = True, "file_fallback"
                    return action
                except (ParseError, SyntaxError, ValueError):
                    raise edit_error
        self.method = "file"
        action = parse_file_content(text, path)
        self.recovered = len(file_blocks(text)) > 1
        return action
