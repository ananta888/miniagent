import tempfile
import unittest
import hashlib
import ast
from pathlib import Path

from miniagent.gates.pipeline import PathGate
from miniagent.parsing.file_parser import parse_file_content
from miniagent.parsing.json_parser import ParseError
from miniagent.parsing.line_edit_parser import parse_line_edit
from miniagent.parsing.function_edit_parser import parse_function_edit
from miniagent.state.models import AgentState, PlanStep, RuntimeOptions, StepState, ToolPolicy
from miniagent.state.models import ModelConfig, RunLimits
from miniagent.state.manager import StateManager
from miniagent.model.base import ModelResponse
from miniagent.runtime import Runtime
from miniagent.prompts.builder import PromptBuilder
from miniagent.tools.registry import ToolRegistry
from miniagent.tools.base import ToolContext
from miniagent.tools.write_file import WriteFile, WriteFileArgs


class FileParserTests(unittest.TestCase):
    def test_text_file_types_and_markdown_with_nested_fences(self):
        examples = [
            ('README.md', 'markdown', '# Usage\n\n```java\nclass Main {}\n```\n', '````'),
            ('Main.java', 'java', 'class Main { String value = "hello"; }\n', '```'),
            ('web.js', 'javascript', 'const message = "Grüße";\n', '~~~'),
            ('settings.yaml', 'yaml', 'key: "value"\n', '```'),
            ('LICENSE', '', 'Example license text\n', '```'),
            ('data.json', 'json', '{"name": "value"}\n', '```'),
            ('sample.custom', 'unknown', 'arbitrary \\ text\n', '```'),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'input'
            source.mkdir()
            (source / 'SPEC.md').write_text('Write all the specified text files.')
            options = RuntimeOptions(planning_strategy='files', execute_plan=True)
            self.assertEqual(options.file_output_format, 'fenced')
            manager = StateManager.create(root / 'runs', 'Generate text files', ModelConfig(), RunLimits(),
                                          source, ['SPEC.md'], ToolPolicy(write_paths=[e[0] for e in examples]), options)
            class Backend:
                responses = iter(f'{marker}{language}\n{content}{marker}' for _, language, content, marker in examples)
                def generate(self, prompt):
                    return ModelResponse(text=next(self.responses), input_tokens=10, output_tokens=10)
            state = Runtime(manager, Backend()).run()
            self.assertEqual(state.status, 'completed', state.feedback)
            self.assertEqual(state.metrics.llm_calls, len(examples))
            self.assertEqual(state.metrics.parser_recoveries, 0)  # Nested Markdown is ordinary file content.
            for path, _, content, _ in examples:
                with self.subTest(path=path):
                    self.assertEqual((manager.run_dir / 'workspace' / path).read_text(), content)
            self.assertEqual(manager.load().options.file_output_format, 'fenced')

    def test_long_outer_fences_preserve_embedded_markdown_and_newlines(self):
        for marker in ['````', '~~~~']:
            content = '# Example\r\n\r\n```python\r\nx = 1\r\n```\r\n~~~text\r\nhello\r\n~~~\r\n'
            action = parse_file_content(marker + 'markdown\r\n' + content + marker + '\r\n', 'README.md')
            self.assertEqual(action.arguments['content'], content)
        with self.assertRaises(ParseError):
            parse_file_content('````markdown\n# Intro\n```java\nclass Main {}\n```', 'README.md')

    def test_unique_file_selection_is_not_python_specific(self):
        for path, language in [('README.md', 'markdown'), ('Main.java', 'java'), ('a.custom', 'custom')]:
            text = '```' + language + '\nfile body\n```\n```json\n{"example":1}\n```'
            self.assertEqual(parse_file_content(text, path).arguments['content'], 'file body\n')

    def test_explicit_file_task_still_receives_parse_corrections(self):
        state = AgentState(run_id='test', goal='code', started_at=0.0,
                           options=RuntimeOptions(file_output_format='fenced', file_tasks={'app.py': 'Write an API'}))
        state.steps = [StepState(proposal=PlanStep(description='write', tool='write_file', arguments={'path': 'app.py'}))]
        prompts = PromptBuilder(ToolRegistry([]))
        self.assertEqual(prompts.build(state, {}), 'Write an API')
        state.feedback = 'Previous output was truncated; close the code fence.'
        self.assertIn(state.feedback, prompts.build(state, {}))

    def test_one_artifact_with_prose_is_bound_to_planned_path(self):
        action = parse_file_content('Here is the file:\n```python\nx = 1\n```\nExplanation.', 'app.py')
        self.assertEqual(action.tool, 'write_file')
        self.assertEqual(action.arguments, {'path': 'app.py', 'content': 'x = 1\n'})

    def test_ambiguous_or_truncated_artifacts_rejected(self):
        for text in ['x = 1', '```python\nx = 1', '```\n\n```',
                     '```python\nx = 1\n```\n```python\ny = 2\n```', 'x' * 32769]:
            with self.subTest(text=text[:40]), self.assertRaises(ParseError):
                parse_file_content(text, 'app.py')

    def test_unique_python_artifact_can_ignore_json_response_example(self):
        text = '```python\nx = 1\n```\nResponse example:\n```json\n{"value": 1}\n```'
        action = parse_file_content(text, 'app.py')
        self.assertEqual(action.arguments['content'], 'x = 1\n')

    def test_file_mode_cannot_override_path_authority(self):
        with tempfile.TemporaryDirectory() as root:
            context = ToolContext(Path(root), policy=ToolPolicy(write_paths=['app.py']))
            state = AgentState(run_id='test', goal='code', started_at=0.0)
            action = parse_file_content('```python\nx = 1\n```', '../outside.py')
            self.assertFalse(PathGate(context).check(action, state).allowed)
            action = parse_file_content('```python\n# path: ../../outside.py\nx = 1\n```', 'app.py')
            self.assertEqual(action.arguments['path'], 'app.py')

    def test_line_edit_preserves_scope_indentation_and_checks_syntax(self):
        source = 'def increment(n):\n    return n - 1\n'
        action = parse_line_edit('{"line":2,"replacement":"return n + 1"}', 'app.py', source, None)
        self.assertEqual(action.arguments['content'], 'def increment(n):\n    return n + 1\n')
        for text in ['{"line":3,"replacement":"pass"}', '{"line":1,"replacement":"return n"}',
                     '{"line":2,"replacement":"return n - 1"}', '{"line":"2","replacement":"pass"}',
                     '{"line":2,"line":1,"replacement":"pass"}']:
            with self.subTest(text=text), self.assertRaises(ParseError):
                parse_line_edit(text, 'app.py', source, None)

    def test_line_edit_rejects_stale_source_before_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = 'value = 1\n'
            (root / 'app.py').write_text(original)
            digest = hashlib.sha256(original.encode()).hexdigest()
            action = parse_line_edit('{"line":1,"replacement":"value = 2"}', 'app.py', original, digest)
            (root / 'app.py').write_text('other writer\n')
            context = ToolContext(root, policy=ToolPolicy(write_paths=['app.py']))
            with self.assertRaisesRegex(ValueError, 'File changed'):
                WriteFile().execute(WriteFileArgs.model_validate(action.arguments), context)
            self.assertEqual((root / 'app.py').read_text(), 'other writer\n')

    def test_line_edit_rejects_syntax_that_only_fails_compilation(self):
        with self.assertRaises(ParseError):
            parse_line_edit('{"line":1,"replacement":"return 42"}', 'app.py', 'value = 1\n', None)

    def test_function_edit_preserves_other_code_and_decorators(self):
        source = 'import math\n@route("/value")\ndef value(n):\n    return n - 1\n\ndef other():\n    return 9\n'
        target = ast.parse(source).body[1]
        response = '```python\nimport os\ndef value(n):\n    return n + 1\ndef other():\n    return 0\n```'
        action = parse_function_edit(response, 'app.py', source, target, 'a' * 64)
        self.assertEqual(action.arguments['content'], source.replace('n - 1', 'n + 1'))
        self.assertEqual(action.arguments['expected_hash'], 'a' * 64)
        for code in ['def renamed(n):\n    return n', 'def value(x):\n    return x',
                     '@other_route\ndef value(n):\n    return n',
                     'def value(n):\n    return n\ndef value(n):\n    return 0']:
            with self.subTest(code=code), self.assertRaises(ParseError):
                parse_function_edit('```python\n' + code + '\n```', 'app.py', source, target, None)
