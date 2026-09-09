import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import tomllib
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from examples.fibonacci_flask.demo import HERE, ScriptedCodingBackend, create_run
from miniagent.gates.pipeline import BudgetGate, CommandGate, CompletionGate, FailureGate, PathGate, StepGate
from miniagent.runtime import Runtime
from miniagent.planning.planner import Planner
from miniagent.state.models import AgentState, FinalAction, ModelConfig, PlanAction, PlanStep, RunLimits, RuntimeOptions, StepState, ToolAction, ToolPolicy
from miniagent.model.base import ModelResponse
from miniagent.state.observations import ObservationStore
from miniagent.tools.base import ToolContext
from miniagent.tools.shell import Shell, ShellArgs, run_command
from miniagent.tools.write_file import WriteFile, WriteFileArgs


class CodingToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.policy = ToolPolicy(write_paths=["app.py"], command_timeout_seconds=2.0)
        self.context = ToolContext(self.root, output_limit=256, policy=self.policy)

    def test_atomic_write_and_overwrite(self):
        tool = WriteFile()
        tool.execute(WriteFileArgs(path="app.py", content="old"), self.context)
        with patch("miniagent.state.files.os.replace", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                tool.execute(WriteFileArgs(path="app.py", content="partial"), self.context)
        self.assertEqual((self.root / "app.py").read_text(), "old")
        result = tool.execute(WriteFileArgs(path="app.py", content="new"), self.context)
        self.assertTrue(result.success)
        self.assertEqual((self.root / "app.py").read_text(), "new")
        self.assertEqual(list(self.root.glob(".app.py.*")), [])

    def test_write_allowlist_and_traversal(self):
        state = AgentState(run_id="test", goal="code", started_at=time.time())
        for path in ["SPEC.md", "../app.py", "/tmp/app.py", "C:\\app.py"]:
            with self.subTest(path=path):
                action = ToolAction(type="tool", tool="write_file", arguments={"path": path, "content": "x"})
                self.assertFalse(PathGate(self.context).check(action, state).allowed)
                with self.assertRaises(ValueError):
                    WriteFile().execute(WriteFileArgs(path=path, content="x"), self.context)

    def test_write_rejects_symlink_to_other_workspace_file(self):
        protected = self.root / "SPEC.md"
        protected.write_text("protected")
        (self.root / "app.py").symlink_to(protected)
        with self.assertRaisesRegex(ValueError, "symlink"):
            WriteFile().execute(WriteFileArgs(path="app.py", content="overwrite"), self.context)
        self.assertEqual(protected.read_text(), "protected")

    def test_write_rejects_oversized_utf8(self):
        with self.assertRaisesRegex(ValueError, "32 KiB"):
            WriteFile().execute(WriteFileArgs(path="app.py", content="😀" * 9000), self.context)

    def test_unknown_commands_blocked_in_gate_and_tool(self):
        state = AgentState(run_id="test", goal="code", started_at=time.time(), policy=self.policy)
        action = ToolAction(type="tool", tool="shell", arguments={"command": "rm -rf /"})
        self.assertFalse(CommandGate().check(action, state).allowed)
        with self.assertRaisesRegex(ValueError, "not configured"):
            Shell().execute(ShellArgs(command="unconfigured"), self.context)

    def test_commands_are_argv_not_shell_text(self):
        result = run_command([sys.executable, "-c", "import sys;print(sys.argv[1])", "$(touch unwanted); echo hello"], self.context)
        self.assertTrue(result.success)
        self.assertIn("$(touch unwanted)", result.output)
        self.assertFalse((self.root / "unwanted").exists())

    def test_command_exit_and_output(self):
        result = run_command([sys.executable, "-c", "import sys;print('failure details');sys.exit(7)"], self.context)
        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, 7)
        self.assertIn("failure details", result.output)

    def test_output_is_bounded(self):
        result = run_command([sys.executable, "-c", "print('x'*100000)"], self.context)
        self.assertTrue(result.success)
        self.assertEqual(len(result.output), 256)
        self.assertTrue(result.metadata["truncated"])

    def test_timeout_including_closed_stdout(self):
        context = ToolContext(self.root, policy=ToolPolicy(command_timeout_seconds=0.15))
        for code in ["import time;time.sleep(10)", "import os,time;os.close(1);os.close(2);time.sleep(10)"]:
            with self.subTest(code=code):
                started = time.monotonic()
                result = run_command([sys.executable, "-c", code], context)
                self.assertFalse(result.success)
                self.assertTrue(result.metadata["timed_out"])
                self.assertLess(time.monotonic() - started, 2)

    def test_runtime_deadline_limits_command_timeout(self):
        context = ToolContext(self.root, policy=ToolPolicy(command_timeout_seconds=20.0),
                              deadline=time.time() + 0.1)
        started = time.monotonic()
        result = run_command([sys.executable, "-c", "import time;time.sleep(10)"], context)
        self.assertTrue(result.metadata["timed_out"])
        self.assertLess(time.monotonic() - started, 2)
        with patch("miniagent.tools.shell.subprocess.Popen", side_effect=AssertionError("Already expired")):
            result = run_command([sys.executable], context)
        self.assertFalse(result.success)

    def test_child_process_does_not_survive_parent(self):
        child = "import time,pathlib;time.sleep(0.5);pathlib.Path('escaped').write_text('bad')"
        parent = f"import subprocess,sys;subprocess.Popen([sys.executable,'-c',{child!r}])"
        result = run_command([sys.executable, "-c", parent], self.context)
        self.assertTrue(result.success)
        time.sleep(0.6)
        self.assertFalse((self.root / "escaped").exists())

    def test_no_interactive_input_or_inherited_credentials(self):
        with patch.dict(os.environ, {"MINIAGENT_TEST_SECRET": "must-not-inherit"}):
            code = "import os,sys;print('MINIAGENT_TEST_SECRET' in os.environ);print(repr(sys.stdin.read()))"
            result = run_command([sys.executable, "-c", code], self.context)
        self.assertTrue(result.success)
        self.assertEqual(result.output, "False\n''\n")

    def test_source_mutation_invalidates_verification(self):
        (self.root / "app.py").write_text("original")
        self.policy.commands = {"verify": [sys.executable, "-c", "from pathlib import Path;Path('app.py').write_text('changed')"]}
        result = Shell().execute(ShellArgs(command="verify"), self.context)
        self.assertFalse(result.success)
        self.assertIn("changed during verification", result.error)
        self.assertNotIn("verification_digest", result.metadata)

    def test_required_command_must_exist(self):
        with self.assertRaises(ValidationError):
            ToolPolicy(required_verifications=["missing"])

    def test_replans_are_bounded(self):
        state = AgentState(run_id="test", goal="code", started_at=time.time())
        step = PlanStep(description="Read", tool="read_file", arguments={"path": "a"})
        state.steps = [StepState(proposal=step)]
        action = PlanAction(type="plan", steps=[step])
        self.assertFalse(StepGate().check(action, state).allowed)
        state.consecutive_failures = 1
        self.assertTrue(StepGate().check(action, state).allowed)
        state.replans = state.limits.max_replans
        self.assertTrue(StepGate().check(action, state).terminal)

    def test_configurable_replan_limits_and_persistence(self):
        step = PlanStep(description="Read", tool="read_file", arguments={"path": "a"})
        action = PlanAction(type="plan", steps=[step])
        for setting in [0, 10, 20, "unlimited"]:
            with self.subTest(setting=setting):
                value = json.dumps(setting)
                limits = RunLimits.model_validate(tomllib.loads(f"[limits]\nmax_replans = {value}")["limits"])
                state = AgentState(run_id="test", goal="code", started_at=time.time(), limits=limits,
                                   steps=[StepState(proposal=step)], consecutive_failures=1)
                state = AgentState.model_validate_json(state.model_dump_json())
                self.assertEqual(state.limits.max_replans, setting)
                if setting == "unlimited":
                    state.replans = 1000000
                    self.assertTrue(StepGate().check(action, state).allowed)
                    state.iteration = limits.max_iterations + 1
                    self.assertTrue(BudgetGate().check(action, state).terminal)
                    state.consecutive_failures = limits.max_consecutive_failures
                    self.assertTrue(FailureGate().check(action, state).terminal)
                else:
                    if setting:
                        state.replans = setting - 1
                        self.assertTrue(StepGate().check(action, state).allowed)
                    state.replans = setting
                    self.assertTrue(StepGate().check(action, state).terminal)
        for invalid in [-1, 2.5, True, "20", "infinite"]:
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                RunLimits(max_replans=invalid)

    def test_long_replanning_keeps_compact_state_and_explicit_evidence(self):
        state = AgentState(run_id="test", goal="code", started_at=time.time(), verified_reads=["SPEC.md"])
        state.verifications = {"verify": "source-digest"}
        action = PlanAction(type="plan", steps=[PlanStep(description="Read", tool="read_file", arguments={"path": "SPEC.md"})])
        planner = Planner()
        for iteration in range(100):
            planner.apply(action, state)
            self.assertLessEqual(len(state.steps), 13)
            state.current_step.observation_id = f"obs-{iteration}"
        self.assertEqual(state.replans, 99)
        self.assertEqual(state.verified_reads, ["SPEC.md"])
        self.assertEqual(state.verifications, {"verify": "source-digest"})


@unittest.skipUnless(importlib.util.find_spec("flask"), "Install .[examples] for Flask coding tests")
class FibonacciWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.manager = create_run(Path(self.temp.name) / "runs", ModelConfig(max_new_tokens=1536))

    def test_generate_fail_replan_fix_verify_complete(self):
        self.assertFalse((self.manager.run_dir / "workspace/app.py").exists())
        model = ScriptedCodingBackend()
        state = Runtime(self.manager, model).run()
        self.assertEqual(state.status, "completed", state.feedback)
        self.assertEqual(state.replans, 1)
        self.assertEqual(state.tool_calls, 6)
        self.assertEqual(state.metrics.failed_tools, 1)
        self.assertEqual(state.iteration, 9)
        self.assertIn("Command exited 1", model.prompts[5])
        self.assertIn("AssertionError", model.prompts[5])
        self.assertIn("Execute CURRENT STEP now", model.prompts[6])
        self.assertNotIn("Return only a plan", model.prompts[6])
        self.assertNotIn("<complete file content>", model.prompts[2])
        observations = ObservationStore(self.manager.run_dir).recent(10)
        verifications = [o for o in observations if o.tool == "shell"]
        self.assertEqual([o.exit_code for o in verifications], [1, 0])
        artifact = json.loads((self.manager.run_dir / verifications[-1].raw_output_ref).read_text())
        self.assertIn('"tests_run": 12, "failures": 0, "errors": 0', artifact["output"])
        self.assertIn("verify", state.verifications)
        self.assertEqual((self.manager.run_dir / "workspace/app.py").read_text(), (HERE / "reference_app.py").read_text())
        self.assertNotIn("value=a + 1", model.prompts[-1])  # write bodies stay out of recent context
        self.assertIn("Support every integer n from 0 through 1000", model.prompts[-1])
        self.assertIn("SPEC.md", state.required_read_summaries)

    def test_changed_code_requires_new_verification(self):
        state = Runtime(self.manager, ScriptedCodingBackend()).run()
        context = ToolContext(self.manager.run_dir / "workspace", policy=state.policy)
        final = FinalAction(type="final", answer="All tests pass")
        self.assertTrue(CompletionGate(context).check(final, state).allowed)
        (context.workspace / "app.py").write_text("broken")
        self.assertFalse(CompletionGate(context).check(final, state).allowed)

    def test_declared_modular_plan_uses_model_only_for_code_and_binds_all_files(self):
        options = RuntimeOptions(file_output_format="fenced", planning_strategy="files", execute_plan=True)
        manager = create_run(Path(self.temp.name) / "modular", ModelConfig(),
                             RunLimits(max_tokens=4616), options, modular=True)
        class Backend:
            responses = iter(['```python\ndef fibonacci(n):\n    return n\n```',
                              '```python\n' + (HERE / 'reference_app.py').read_text() + '\n```',
                              '```text\nFlask>=3.1,<4\n```'])
            prompts = []
            def generate(self, prompt):
                self.prompts.append(prompt)
                return ModelResponse(text=next(self.responses), input_tokens=2, output_tokens=2)
        backend = Backend()
        state = Runtime(manager, backend).run()
        self.assertEqual(state.status, "completed", state.feedback)
        self.assertEqual(state.metrics.llm_calls, 3)
        self.assertEqual(state.tool_calls, 5)
        self.assertIn("Write the Python function fibonacci", backend.prompts[0])
        self.assertIn("Import fibonacci from logic", backend.prompts[1])
        # Even an unused allowed module is bound to the successful verification.
        context = ToolContext(manager.run_dir / "workspace", policy=state.policy)
        (context.workspace / "logic.py").write_text('changed = True\n')
        self.assertFalse(CompletionGate(context).check(FinalAction(type="final", answer="done"), state).allowed)

    def test_fenced_files_and_runtime_repair_preserve_error_and_source(self):
        state = self.manager.load()
        state.options = RuntimeOptions(file_output_format="fenced", repair_strategy="rewrite")
        self.manager.save(state)
        scripted = list(ScriptedCodingBackend().responses)
        # The runtime supplies the repair plan, including both writable files.
        scripted = scripted[:5] + [scripted[6], scripted[3], scripted[7], scripted[8]]
        class Backend:
            def __init__(self):
                self.actions = iter(scripted)
                self.prompts = []
            def generate(self, prompt):
                self.prompts.append(prompt)
                action = next(self.actions)
                if action.get("tool") == "write_file":
                    text = "```\n" + action["arguments"]["content"] + "\n```"
                else:
                    text = json.dumps(action)
                return ModelResponse(text=text, input_tokens=100, output_tokens=500)
        model = Backend()
        state = Runtime(self.manager, model).run()
        self.assertEqual(state.status, "completed", state.feedback)
        self.assertEqual(state.replans, 1)
        self.assertEqual(state.iteration, state.metrics.llm_calls + 1)
        self.assertIn("value=a + 1", model.prompts[5])
        self.assertIn("AssertionError", model.prompts[5])
        self.assertIn("AssertionError", model.prompts[6])  # retained across the successful write
        self.assertIsNone(state.repair_feedback)

    def test_runtime_repair_still_obeys_replan_gate(self):
        state = self.manager.load()
        state.options.repair_strategy = "rewrite"
        state.limits.max_replans = 0
        self.manager.save(state)
        state = Runtime(self.manager, ScriptedCodingBackend()).run()
        self.assertEqual(state.status, "blocked")
        self.assertEqual(state.feedback, "Replan budget reached")
        self.assertEqual(state.metrics.llm_calls, 5)

    def test_false_completion_after_failed_tests_is_blocked(self):
        model = ScriptedCodingBackend()
        actions = list(model.responses)[:5]
        actions += [{"type": "final", "answer": "All tests pass"}] * self.manager.load().limits.max_blocked_actions
        model.responses = iter(actions)
        state = Runtime(self.manager, model).run()
        self.assertEqual(state.status, "blocked")
        self.assertIsNone(state.answer)
        self.assertNotIn("verify", state.verifications)

    def test_interrupted_write_is_not_replayed(self):
        with patch.object(WriteFile, "execute", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                Runtime(self.manager, ScriptedCodingBackend()).run()
        self.assertEqual(self.manager.load().pending_action.tool, "write_file")
        with patch.object(WriteFile, "execute", side_effect=AssertionError("Must not replay")):
            state = Runtime(self.manager, ScriptedCodingBackend()).run()
        self.assertEqual(state.status, "blocked")
        self.assertIn("explicit recovery", state.feedback)

    def test_interrupted_shell_is_not_replayed(self):
        with patch.object(Shell, "execute", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                Runtime(self.manager, ScriptedCodingBackend()).run()
        with patch.object(Shell, "execute", side_effect=AssertionError("Must not replay")):
            state = Runtime(self.manager, ScriptedCodingBackend()).run()
        self.assertEqual(state.status, "blocked")

    def test_completed_write_observation_recovers_without_reexecution(self):
        original = ObservationStore.record
        def interrupt_after_write(store, iteration, action, result):
            observation = original(store, iteration, action, result)
            if action.tool == "write_file":
                raise KeyboardInterrupt()
            return observation
        with patch.object(ObservationStore, "record", interrupt_after_write):
            with self.assertRaises(KeyboardInterrupt):
                Runtime(self.manager, ScriptedCodingBackend()).run()
        model = ScriptedCodingBackend()
        model.responses = iter(list(model.responses)[3:])
        state = Runtime(self.manager, model).run()
        self.assertEqual(state.status, "completed", state.feedback)
        self.assertEqual(state.tool_calls, 6)
