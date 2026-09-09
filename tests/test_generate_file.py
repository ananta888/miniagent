import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from examples.generate_file import create_run, main
from miniagent.model.base import ModelResponse
from miniagent.runtime import Runtime
from miniagent.state.models import ModelConfig, RunLimits


class GenerateFileTests(unittest.TestCase):
    def test_html_generation_with_real_tools_and_parse_correction(self):
        class Backend:
            prompts = []
            responses = iter(['```html\ntruncated', '```html\n<!doctype html><title>Tetris</title>\n```'])

            def generate(self, prompt):
                self.prompts.append(prompt)
                return ModelResponse(text=next(self.responses), input_tokens=10, output_tokens=20)

        with tempfile.TemporaryDirectory() as directory:
            manager = create_run(Path(directory), 'Create Tetris', 'web/index.html', ModelConfig(), RunLimits())
            backend = Backend()
            state = Runtime(manager, backend).run()
            self.assertEqual(state.status, 'completed', state.feedback)
            self.assertEqual((manager.run_dir / 'workspace/web/index.html').read_text(),
                             '<!doctype html><title>Tetris</title>\n')
            self.assertEqual(len(backend.prompts), 2)
            self.assertIn('Create Tetris', backend.prompts[1])
            self.assertEqual(manager.load().policy.write_paths, ['web/index.html'])
            # A terminal resume does not need a server or inference.
            with patch('examples.generate_file.LocalLlamaBackend.request', side_effect=AssertionError):
                self.assertEqual(main(['--resume', str(manager.run_dir)]), 0)

    def test_destination_cannot_escape_or_replace_input(self):
        with tempfile.TemporaryDirectory() as directory:
            for output in ['../outside.html', '/tmp/outside.html', 'SPEC.md', './SPEC.md']:
                with self.subTest(output=output), self.assertRaises(ValueError):
                    create_run(Path(directory), 'Task', output, ModelConfig(), RunLimits())

    def test_cli_discovers_model_and_writes_non_python_file(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('examples.generate_file.LocalLlamaBackend.request', return_value={'model_path': '/models/local.gguf'}), \
                 patch('examples.generate_file.LocalLlamaBackend.generate', return_value=ModelResponse(
                     text='```markdown\n# Hello\n```', input_tokens=10, output_tokens=10)):
                self.assertEqual(main(['Write a greeting', '--output', 'README.md', '--runs-dir', directory]), 0)
            output = list(Path(directory).glob('*/workspace/README.md'))
            self.assertEqual(len(output), 1)
            self.assertEqual(output[0].read_text(), '# Hello\n')
