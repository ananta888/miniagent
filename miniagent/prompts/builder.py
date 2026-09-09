import json
from importlib.resources import files
from pathlib import Path

from miniagent.state.models import AgentState
from miniagent.tools.registry import ToolRegistry
from miniagent.parsing.function_edit_parser import function_target


class PromptBuilder:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def build(self, state: AgentState, context: dict) -> str:
        if (state.options.file_output_format == "fenced" and not state.needs_replan
                and state.current_step and state.current_step.proposal.tool == "write_file"):
            return self.file_prompt(state, context)
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

    def file_prompt(self, state: AgentState, context: dict) -> str:
        path = state.current_step.proposal.arguments["path"]
        repairing = bool(state.repair_feedback) and (not state.options.repair_paths or path in state.options.repair_paths)
        target = function_target(state, context) if repairing else None
        file_task = state.options.file_tasks.get(path)
        if file_task and not repairing and not state.feedback:
            return file_task
        sections = [f"Write {path} for this task. Return the complete file in one code fence. No JSON action.",
                    "TASK\n" + (file_task or state.goal)]
        if not repairing and path.endswith(".py"):
            sections.append("Use small helper functions for separate responsibilities.")
        for name, summary in ({} if file_task else state.required_read_summaries).items():
            sections.append(f"SPECIFICATION ({name})\n{summary}")
        line_edit = state.options.repair_edit == "line" and repairing and context.get("CURRENT FILE")
        replace_edit = state.options.repair_edit == 'replace' and repairing and context.get('CURRENT FILE')
        fresh = state.stalled_verifications >= state.options.fresh_after and repairing and not line_edit and not target and not replace_edit
        if context.get("CURRENT FILE") and not fresh:
            label = "BEST TESTED FILE TO CORRECT" if state.options.keep_best and state.best_attempt else "CURRENT FILE TO CORRECT"
            source = context["CURRENT FILE"]
            if target:
                source = "\n".join(source.splitlines()[target.lineno - 1:target.end_lineno])
            elif line_edit:
                source = "\n".join(f"{i}: {line}" for i, line in enumerate(source.splitlines(), 1))
            sections.append(label + "\n" + source)
        repair_feedback = context.get("REPAIR FEEDBACK") if repairing else None
        if repair_feedback:
            # One concrete counterexample is easier to act on than many repeated failures.
            failures = repair_feedback.split("\nFAIL ")
            focus = failures[0] + ("\nFAIL " + failures[1] if len(failures) > 1 else "")
            sections.append(f"FIRST FAILING TEST TO FIX (repair {state.replans})\n" + focus)
            sections.append("Make the code satisfy this test. Change the implementation; do not copy the broken code unchanged. "
                            "Other tests will run again afterward. Return the complete corrected file.")
        if fresh:
            sections.append("The same implementation failed repeatedly. Write a fresh implementation from the specification. "
                            "Break the problem into small helper functions for validation, calculation and response construction.")
        if state.feedback and not state.needs_replan and state.feedback != state.repair_feedback:
            sections.append("OUTPUT CORRECTION\n" + state.feedback)
        kind = ""
        if Path(path).name == "requirements.txt":
            kind = "This is a pip dependency manifest: package requirements only, one per line. No Python code. "
        elif Path(path).suffix == ".py":
            kind = "This file must contain executable Python source. "
        sections.append(f"OUTPUT ONLY {path}\n{kind}One code fence containing only this file. Do not output any other file. "
                        "If the file contains code fences, use an outer fence longer than every fence inside the file.")
        if replace_edit:
            sections[0] = f'Fix one localized part of {path} to address the first failing test.'
            sections[-1] = ('Return exactly two closed code fences. First use label before and copy the exact '
                            'existing faulty fragment, including indentation, which must occur once in the file. '
                            'Then use label after with its corrected replacement. No JSON. No other files. '
                            'Keep the rest of the file unchanged; prefer a small edit over rewriting everything.\n'
                            'REPAIR FORMAT (overrides original file-generation format):\n'
                            '```before\nexact faulty source fragment\n```\n'
                            '```after\ncorrected source fragment, different from before\n```')
            sections = [s for s in sections if not s.startswith('Make the code satisfy')]
        elif target:
            sections[0] = f"Correct the Python function {target.name} in {path}. The runtime preserves the rest of the file."
            sections[-1] = (f"Return only the complete corrected definition of {target.name} in one Python code fence. "
                            "Keep its function name and arguments. Do not include imports or other functions.")
            sections = [s for s in sections if not s.startswith("Make the code satisfy")]
        elif line_edit:
            sections[0] = f"Fix one line in {path} to address the failing test."
            sections[-1] = ("OUTPUT: JSON with line (1-based integer) and replacement (string). "
                            "Replace one existing line; replacement may contain multiple lines. "
                            "The runtime preserves that line's indentation. Return replacement without its base indentation. "
                            "Do not return the complete file. Choose a line that fixes the reported failure.")
            sections = [s for s in sections if not s.startswith("Make the code satisfy")]
        return "\n\n".join(sections)
