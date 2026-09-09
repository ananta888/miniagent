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
    def test_legacy_run_keeps_json_protocol_on_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = StateManager.create(Path(directory), "Inspect", ModelConfig(), RunLimits())
            path = manager.run_dir / "state.json"
            saved = json.loads(path.read_text())
            del saved["options"]
            path.write_text(json.dumps(saved))
            state = manager.load()
            self.assertEqual(state.options.file_output_format, "json")
            manager.save(state)
            self.assertEqual(manager.load().options.file_output_format, "json")

    def test_explicit_resume_config_preserves_goal_evidence_and_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = StateManager.create(root / "runs", "Original goal", ModelConfig(), RunLimits())
            state = manager.load()
            state.status = "blocked"
            state.iteration, state.tool_calls, state.token_budget_used, state.replans = 9, 5, 1234, 2
            state.verified_reads = ["SPEC.md"]
            state.verifications = {"verify": "digest"}
            state.parse_failures = 5
            manager.save(state)
            config = root / "resume.toml"
            config.write_text('[limits]\nmax_replans=40\n[runtime]\nfile_output_format="fenced"\n')
            def no_inference(runtime):
                resumed = runtime.manager.load()
                self.assertEqual(resumed.status, "running")
                self.assertEqual(resumed.goal, "Original goal")
                self.assertEqual((resumed.iteration, resumed.tool_calls, resumed.token_budget_used, resumed.replans), (9, 5, 1234, 2))
                self.assertEqual(resumed.verified_reads, ["SPEC.md"])
                self.assertEqual(resumed.verifications, {"verify": "digest"})
                self.assertEqual(resumed.parse_failures, 0)
                self.assertEqual(resumed.limits.max_replans, 40)
                self.assertEqual(resumed.options.file_output_format, "fenced")
                return resumed
            with patch("miniagent.cli.Runtime.run", no_inference), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["resume", str(manager.run_dir), "--config", str(config), "--retry-blocked"]), 1)
            events = [json.loads(line) for line in (manager.run_dir / "events.jsonl").read_text().splitlines()]
            self.assertEqual(events[-1]["event"], "resume_configured")

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
