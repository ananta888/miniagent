import ast

from miniagent.parsing.file_parser import parse_file_content
from miniagent.parsing.json_parser import ParseError
from miniagent.state.models import AgentState, ToolAction


def function_target(state: AgentState, context: dict) -> ast.FunctionDef | None:
    if not state.current_step or not state.repair_feedback or not context.get("CURRENT FILE"):
        return None
    path = state.current_step.proposal.arguments.get("path")
    if state.options.repair_paths and path not in state.options.repair_paths:
        return None
    names = state.options.repair_functions.get(path, [])
    if not names:
        return None
    try:
        functions = {node.name: node for node in ast.parse(context["CURRENT FILE"]).body if isinstance(node, ast.FunctionDef)}
    except SyntaxError:
        return None
    available = [functions[name] for name in names if name in functions]
    return available[(state.replans - 1) % len(available)] if available else None


def parse_function_edit(text: str, path: str, source: str, target: ast.FunctionDef,
                        expected_hash: str | None) -> ToolAction:
    code = parse_file_content(text, path).arguments["content"]
    try:
        module = ast.parse(code)
        matches = [node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == target.name]
        if len(matches) != 1:
            raise ValueError(f"Return one unambiguous definition of {target.name}")
        replacement = matches[0]
        if replacement.name != target.name or ast.dump(replacement.args) != ast.dump(target.args):
            raise ValueError(f"Keep the function name and arguments of {target.name}")
        if replacement.decorator_list:
            if [ast.dump(d) for d in replacement.decorator_list] != [ast.dump(d) for d in target.decorator_list]:
                raise ValueError("Keep the existing decorators")
        # Other code in the response is never applied. Existing decorators stay.
        code = "".join(code.splitlines(keepends=True)[replacement.lineno - 1:replacement.end_lineno])
        lines = source.splitlines(keepends=True)
        lines[target.lineno - 1:target.end_lineno] = [code.rstrip() + "\n"]
        content = "".join(lines)
        compile(content, path, "exec")
    except (SyntaxError, ValueError, RecursionError) as error:
        raise ParseError(f"Invalid function edit: {str(error)[:400]}") from error
    return ToolAction(type="tool", tool="write_file", arguments={
        "path": path, "content": content, "expected_hash": expected_hash,
    })
