import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from miniagent.execution.checkpoints import keep_checkpoint
from miniagent.state.context import ContextBuilder
from miniagent.state.models import AgentState, PlanStep, RuntimeOptions, StepState, ToolAction, ToolPolicy, ToolResult
from miniagent.state.observations import ObservationStore
from miniagent.testing import run_contract
from miniagent.tools.base import ToolContext


class CheckpointTests(unittest.TestCase):
    def test_regression_uses_best_source_and_matching_feedback_after_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "workspace").mkdir()
            (root / "artifacts").mkdir()
            (root / "observations.jsonl").touch()
            policy = ToolPolicy(write_paths=["app.py"], commands={"verify": ["python"]}, required_verifications=["verify"])
            context = ToolContext(root / "workspace", policy=policy)
            state = AgentState(run_id="test", goal="code", started_at=0.0, policy=policy,
                               options=RuntimeOptions(keep_best=True), repair_feedback="latest error")
            state.steps = [StepState(proposal=PlanStep(description="Fix", tool="write_file", arguments={"path": "app.py"}))]
            store = ObservationStore(root)
            action = ToolAction(type="tool", tool="shell", arguments={"command": "verify"})
            for index, (passed, failures, expected) in enumerate([(8, 4, True), (5, 7, False), (8, 5, False), (9, 3, True)]):
                source = f"version = {index}\n"
                (context.workspace / "app.py").write_text(source)
                report = json.dumps({"miniagent_verification": {"tests_run": 12, "tests_passed": passed, "failures": failures, "errors": 0}})
                obs = store.record(index, action, ToolResult(success=False, output=f"error {index}\n{report}", exit_code=1))
                self.assertEqual(keep_checkpoint(state, obs, root, context), expected)
                if expected:
                    best_source, best_feedback = source, obs.summary
                state = AgentState.model_validate_json(state.model_dump_json())
                built = ContextBuilder(store, context).build(state)
                self.assertEqual(built["CURRENT FILE"], best_source)
                self.assertEqual(built["REPAIR FEEDBACK"], best_feedback)
                self.assertNotIn("verify", state.verifications)  # score cannot grant completion
            state.options.keep_best = False
            (context.workspace / "app.py").write_text("latest = True\n")
            built = ContextBuilder(store, context).build(state)
            self.assertEqual(built["CURRENT FILE"], "latest = True\n")
            self.assertEqual(built["REPAIR FEEDBACK"], "latest error")

    def test_contract_report_contains_assertion_and_does_not_accept_skips(self):
        class Contract(unittest.TestCase):
            def test_failure(self):
                self.assertEqual({"value": 1}, {"value": 2})
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertFalse(run_contract(unittest.defaultTestLoader.loadTestsFromTestCase(Contract), 1))
        self.assertIn("AssertionError", output.getvalue())
        self.assertIn('"tests_passed": 0', output.getvalue())
        class Skipped(unittest.TestCase):
            @unittest.skip("unavailable")
            def test_skipped(self):
                pass
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(run_contract(unittest.defaultTestLoader.loadTestsFromTestCase(Skipped), 1))
