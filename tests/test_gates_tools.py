import os
import tempfile
import time
import unittest
from pathlib import Path

from miniagent.execution.executor import Executor
from miniagent.gates.pipeline import (ArgumentGate, BudgetGate, CompletionGate, FailureGate,
                                     GatePipeline, LoopGate, PathGate, SchemaGate, ToolGate, signature)
from miniagent.state.models import AgentState, FinalAction, PlanStep, StepState, ToolAction
from miniagent.tools.base import ToolContext
from miniagent.tools.list_files import ListFiles
from miniagent.tools.read_file import ReadFile
from miniagent.tools.registry import ToolRegistry


class GateToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.root.mkdir()
        self.context = ToolContext(self.root, output_limit=32)
        self.registry = ToolRegistry([ReadFile(), ListFiles()])
        self.gates = GatePipeline([SchemaGate(), ToolGate(self.registry), ArgumentGate(self.registry), PathGate(self.context)])
        self.executor = Executor(self.registry, self.context, self.gates)
        self.state = AgentState(run_id="test", goal="Read", started_at=time.time())

    def action(self, path="a", tool="read_file"):
        return ToolAction(type="tool", tool=tool, arguments={"path": path})

    def test_registry_rejects_duplicates(self):
        with self.assertRaises(ValueError):
            ToolRegistry([ReadFile(), ReadFile()])
        self.assertIsNone(self.registry.get("unknown"))
        self.assertEqual(len(self.registry.definitions()), 2)

    def test_unknown_and_invalid_arguments(self):
        for action in [self.action(tool="shell"), self.action(123), self.action(True),
                       ToolAction(type="tool", tool="read_file", arguments={}),
                       ToolAction(type="tool", tool="read_file", arguments={"path":"a", "extra":1})]:
            self.assertFalse(self.gates.check(action, self.state).allowed)

    def test_traversal_and_symlink_escape(self):
        outside = Path(self.temp.name) / "secret"
        outside.write_text("secret")
        (self.root / "link").symlink_to(outside)
        (self.root / "dirlink").symlink_to(outside.parent, target_is_directory=True)
        for path in ["../secret", "/etc/shadow", "a/../../secret", "C:\\Windows\\system.ini",
                     "C:secret", "\\\\server\\share", "link", "dirlink/secret", "a\x00"]:
            with self.subTest(path=path):
                self.assertFalse(self.gates.check(self.action(path), self.state).allowed)

    def test_read_list_failure_and_limits(self):
        (self.root / "a").write_text("21\n")
        action = self.action()
        self.assertTrue(self.executor.authorize(action, self.state).allowed)
        result = self.executor.execute_authorized(action)
        self.assertTrue(result.success)
        self.assertEqual(result.output, "21\n")
        listed = self.executor.execute_authorized(self.action(".", "list_files"))
        self.assertEqual(listed.output, "a")
        self.assertFalse(self.executor.execute_authorized(self.action("missing")).success)
        (self.root / "a").write_text("x" * 100)
        result = self.executor.execute_authorized(action)
        self.assertEqual(len(result.output), 32)
        self.assertTrue(result.metadata["truncated"])

    def test_named_pipe_does_not_hang(self):
        os.mkfifo(self.root / "pipe")
        result = self.executor.execute_authorized(self.action("pipe"))
        self.assertFalse(result.success)
        self.assertIn("regular", result.error)

    def test_budgets_and_failures(self):
        self.state.tool_calls = self.state.limits.max_tool_calls
        self.assertFalse(BudgetGate().check(self.action(), self.state).allowed)
        self.state.started_at = time.time() - self.state.limits.max_runtime_seconds - 1
        self.assertFalse(BudgetGate().check(FinalAction(type="final", answer="ok"), self.state).allowed)
        self.state.consecutive_failures = self.state.limits.max_consecutive_failures
        self.assertFalse(FailureGate().check(self.action(), self.state).allowed)

    def test_loop_signature_sorts_arguments(self):
        self.state.last_action = signature(self.action())
        self.state.repeated_action_count = self.state.limits.max_repeated_actions
        self.assertFalse(LoopGate().check(self.action(), self.state).allowed)
        self.assertTrue(LoopGate().check(self.action("b"), self.state).allowed)
        a = ToolAction(type="tool", tool="x", arguments={"a":1,"b":2})
        b = ToolAction(type="tool", tool="x", arguments={"b":2,"a":1})
        self.assertEqual(signature(a), signature(b))

    def test_completion_needs_plan_and_runtime_evidence(self):
        gate = CompletionGate()
        final = FinalAction(type="final", answer="DONE")
        self.assertFalse(gate.check(final, self.state).allowed)
        self.state.steps = [StepState(proposal=PlanStep(description="Read", tool="read_file", arguments={"path":"a"}))]
        self.assertFalse(gate.check(final, self.state).allowed)
        self.state.steps[0].observation_id = "obs-1"
        self.assertFalse(gate.check(final, self.state).allowed)
        self.state.verified_reads = ["a"]
        self.state.required_reads = ["b"]
        self.assertFalse(gate.check(final, self.state).allowed)
        self.state.required_reads = ["a"]
        self.assertTrue(gate.check(final, self.state).allowed)
