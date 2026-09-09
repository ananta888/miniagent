import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from miniagent.model.base import ModelResponse
from miniagent.runtime import Runtime
from miniagent.state.files import append_json, recent_json
from miniagent.state.manager import StateManager
from miniagent.state.models import ModelConfig, RunLimits
from miniagent.state.observations import ObservationStore
from miniagent.tools.read_file import ReadFile


PLAN = {"type": "plan", "steps": [
    {"description": "Read the input", "tool": "read_file", "arguments": {"path": "example.txt"}},
]}
READ = {"type": "tool", "tool": "read_file", "arguments": {"path": "example.txt"}}
FINAL = {"type": "final", "answer": "21 * 2 = 42"}


class FakeBackend:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        value = next(self.responses)
        if isinstance(value, BaseException):
            raise value
        return ModelResponse(text=value if isinstance(value, str) else json.dumps(value), input_tokens=100, output_tokens=50)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = self.root / "source"
        source.mkdir()
        (source / "example.txt").write_text("21\n")
        self.manager = StateManager.create(self.root / "runs", "Double the number", ModelConfig(), RunLimits(), source, ["example.txt"])

    def run_responses(self, responses):
        model = FakeBackend(responses)
        return Runtime(self.manager, model).run(), model

    def test_full_loop_state_context_and_terminal_resume(self):
        state, model = self.run_responses([PLAN, READ, FINAL])
        self.assertEqual(state.status, "completed")
        self.assertEqual(state.tool_calls, 1)
        self.assertEqual(state.metrics.llm_calls, 3)
        self.assertEqual(state.token_budget_used, 450)
        self.assertIn("42", state.answer)
        self.assertIn('"summary": "21\\n"', model.prompts[-1])
        self.assertEqual(self.manager.load(), state)
        self.assertIn("[x] Read the input", (self.manager.run_dir / "plan.md").read_text())
        resumed = Runtime(self.manager, backend_factory=lambda config: self.fail("Model must not load")).run()
        self.assertEqual(resumed.status, "completed")
        events = recent_json(self.manager.run_dir / "events.jsonl", 50)
        self.assertTrue({"run_started", "llm_called", "action_parsed", "gate_passed", "tool_started", "tool_finished", "plan_updated", "run_completed"}.issubset({e["event"] for e in events}))

    def test_invalid_json_gets_corrective_prompt(self):
        state, model = self.run_responses(["not json", PLAN, READ, FINAL])
        self.assertEqual(state.status, "completed")
        self.assertEqual(state.metrics.invalid_actions, 1)
        self.assertIn("could not be parsed", model.prompts[1])

    def test_parse_retries_bounded(self):
        limit = self.manager.load().limits.max_parse_retries
        state, model = self.run_responses(["bad"] * (limit + 1))
        self.assertEqual(state.status, "blocked")
        self.assertEqual(len(model.prompts), limit + 1)
        self.assertEqual(state.tool_calls, 0)

    def test_premature_final_blocked_then_recovered(self):
        state, model = self.run_responses([FINAL, PLAN, READ, FINAL])
        self.assertEqual(state.status, "completed")
        self.assertEqual(state.metrics.blocked_actions, 1)
        self.assertIn("successful, complete observation", model.prompts[1])

    def test_unsafe_plan_never_executes(self):
        bad = {"type":"plan", "steps":[{"description":"Read", "tool":"read_file", "arguments":{"path":"/etc/passwd"}}]}
        with patch.object(ReadFile, "execute", side_effect=AssertionError("Unsafe execution")):
            state, _ = self.run_responses([bad] * 3)
        self.assertEqual(state.status, "blocked")
        self.assertEqual(state.tool_calls, 0)

    def test_recovered_json_still_passes_through_gates(self):
        bad = {"type":"plan", "steps":[{"description":"Read", "tool":"read_file", "arguments":{"path":"/etc/passwd"}}]}
        raw = '```json\n' + json.dumps(bad) + '\n```'
        with patch.object(ReadFile, "execute", side_effect=AssertionError("Unsafe recovery")):
            state, _ = self.run_responses([raw] * 3)
        self.assertEqual(state.status, "blocked")
        self.assertEqual(state.metrics.parser_recoveries, 3)
        self.assertEqual(state.metrics.blocked_actions, 3)
        self.assertEqual(state.tool_calls, 0)

    def test_mislabeled_tool_recovery_does_not_bypass_path_gate(self):
        raw = '{"type":"plan","tool":"read_file","arguments":{"path":"/etc/passwd"}}'
        with patch.object(ReadFile, "execute", side_effect=AssertionError("Unsafe recovery")):
            state, _ = self.run_responses([raw] * 3)
        self.assertEqual(state.status, "blocked")
        self.assertEqual(state.metrics.parser_recoveries, 3)
        self.assertEqual(state.tool_calls, 0)

    def test_iteration_budget_counts_planning(self):
        state = self.manager.load()
        state.limits.max_iterations = 2
        self.manager.save(state)
        state, model = self.run_responses([PLAN, READ, FINAL])
        self.assertEqual(state.status, "blocked")
        self.assertEqual(len(model.prompts), 2)

    def test_insufficient_token_budget_makes_no_model_call(self):
        state = self.manager.load()
        state.limits.max_tokens = 100
        self.manager.save(state)
        state, model = self.run_responses([])
        self.assertEqual(state.status, "blocked")
        self.assertEqual(len(model.prompts), 0)

    def test_model_error_saved(self):
        state, _ = self.run_responses([RuntimeError("out of memory")])
        self.assertEqual(state.status, "failed")
        self.assertIn("out of memory", state.feedback)
        self.assertEqual(self.manager.load().status, "failed")

    def test_failure_limit(self):
        (self.manager.run_dir / "workspace/example.txt").unlink()
        state, _ = self.run_responses([PLAN, READ, READ, READ])
        self.assertEqual(state.status, "blocked")
        self.assertEqual(state.metrics.failed_tools, 3)
        self.assertIsNotNone(state.current_step)

    def test_loop_limit_even_with_higher_failure_budget(self):
        state = self.manager.load()
        state.limits.max_consecutive_failures = 10
        self.manager.save(state)
        (self.manager.run_dir / "workspace/example.txt").unlink()
        state, _ = self.run_responses([PLAN, READ, READ, READ, READ])
        self.assertEqual(state.status, "blocked")
        self.assertEqual(state.tool_calls, 3)
        self.assertEqual(state.metrics.loop_detections, 1)

    def test_truncated_output_is_not_completion_evidence(self):
        (self.manager.run_dir / "workspace/example.txt").write_text("x" * 10000)
        state, _ = self.run_responses([PLAN, READ, READ, READ])
        self.assertEqual(state.status, "blocked")
        self.assertEqual(state.verified_reads, [])

    def test_resume_after_interrupted_model_call(self):
        with self.assertRaises(KeyboardInterrupt):
            self.run_responses([PLAN, KeyboardInterrupt()])
        before = self.manager.load()
        self.assertEqual(before.status, "running")
        self.assertEqual(before.iteration, 2)
        self.assertGreater(before.token_budget_used, 150)
        state, _ = self.run_responses([READ, FINAL])
        self.assertEqual(state.status, "completed")
        self.assertEqual(state.iteration, 4)
        self.assertEqual(state.token_budget_used, before.token_budget_used + 300)

    def test_resume_after_observation_before_state_commit(self):
        original = ObservationStore.record
        def interrupt_after_append(store, *args):
            original(store, *args)
            raise KeyboardInterrupt()
        with patch.object(ObservationStore, "record", interrupt_after_append):
            with self.assertRaises(KeyboardInterrupt):
                self.run_responses([PLAN, READ])
        self.assertIsNotNone(self.manager.load().pending_action)
        with patch.object(ReadFile, "execute", side_effect=AssertionError("Already recorded")):
            state, _ = self.run_responses([FINAL])
        self.assertEqual(state.status, "completed")
        self.assertEqual(state.tool_calls, 1)
        self.assertEqual(state.metrics.successful_tools, 1)
        self.assertEqual(len(ObservationStore(self.manager.run_dir).recent()), 1)

    def test_resume_replays_interrupted_read_once(self):
        with patch.object(ReadFile, "execute", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                self.run_responses([PLAN, READ])
        state, _ = self.run_responses([FINAL])
        self.assertEqual(state.status, "completed")
        self.assertEqual(state.tool_calls, 1)

    def test_goal_changes_rejected_and_plan_projection_repaired(self):
        (self.manager.run_dir / "plan.md").write_text("stale projection")
        with self.manager.lock():
            self.manager.recover()
        self.assertIn("# Goal", (self.manager.run_dir / "plan.md").read_text())
        (self.manager.run_dir / "goal.md").write_text("new goal")
        with self.assertRaisesRegex(ValueError, "implicit goal changes"):
            self.manager.load()

    def test_single_writer_lock(self):
        with self.manager.lock():
            with self.assertRaisesRegex(RuntimeError, "already active"):
                with StateManager(self.manager.run_dir).lock():
                    self.fail("Second writer admitted")

    def test_jsonl_tail_repair_and_bounded_recent_reads(self):
        log = self.manager.run_dir / "events.jsonl"
        for i in range(100):
            append_json(log, {"event": "example", "n": i})
        with log.open("ab") as stream:
            stream.write(b'{"event":')
        with self.manager.lock():
            self.manager.recover()
        self.assertEqual([e["n"] for e in recent_json(log, 4)], [96, 97, 98, 99])
