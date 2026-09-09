import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from miniagent.cli import main
from miniagent.state.manager import StateManager
from miniagent.state.models import ModelConfig, RunLimits


class CLITests(unittest.TestCase):
    def test_status_and_resume_terminal_run_without_loading_model(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = StateManager.create(Path(directory), "Inspect", ModelConfig(), RunLimits())
            state = manager.load()
            state.status = "blocked"
            state.feedback = "Budget reached"
            manager.save(state)
            for command, expected in [("status", 0), ("resume", 1)]:
                with self.subTest(command=command), contextlib.redirect_stdout(io.StringIO()) as output:
                    code = main([command, state.run_id, "--runs-dir", directory])
                self.assertEqual(code, expected)
                self.assertEqual(json.loads(output.getvalue())["status"], "blocked")

    def test_run_reads_config_and_offline_default(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.write_text('[model]\nmodel="local-test"\n[limits]\nmax_iterations=1\n')
            def no_inference(runtime):
                state = runtime.manager.load()
                self.assertTrue(state.model_config_saved.local_files_only)
                self.assertEqual(state.model_config_saved.model, "local-test")
                self.assertEqual(state.limits.max_iterations, 1)
                return state
            with patch("miniagent.cli.Runtime.run", no_inference), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["run", "Inspect", "--config", str(config), "--runs-dir", directory]), 1)

    def test_unknown_configuration_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "bad.toml"
            config.write_text('[unknown]\nflag=true\n')
            with contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertEqual(main(["run", "Inspect", "--config", str(config)]), 2)
            self.assertIn("only accepts", error.getvalue())
