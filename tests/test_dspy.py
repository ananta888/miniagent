import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from miniagent.model.base import ModelResponse
from miniagent.prompts.strategy import ArtifactPromptStrategy, PromptArtifact
from miniagent.state.manager import StateManager
from miniagent.state.models import AgentState, ModelConfig, PlanStep, RunLimits, RuntimeOptions, StepState


class ArtifactTests(unittest.TestCase):
    def test_artifact_validates_fields_and_bounds(self):
        base = dict(instructions="Write code", input_fields=["task"], output_field="response")
        for updates in [dict(demos=[{"task": "missing output"}]), dict(input_fields=["response"]),
                        dict(file_suffixes=["../py"]), dict(demos=[{"task": "x", "response": "x" * 64000}])]:
            with self.subTest(updates=str(updates)[:80]), self.assertRaises(ValidationError):
                PromptArtifact(**{**base, **updates})

    def test_artifact_is_scoped_to_source_files_and_not_planning(self):
        class Baseline:
            def build(self, state, context):
                return "baseline"
        artifact = PromptArtifact(instructions="optimized", input_fields=["task"], output_field="response")
        strategy = ArtifactPromptStrategy(Baseline(), artifact)
        state = AgentState(run_id="test", goal="test", started_at=0.0)
        state.steps = [StepState(proposal=PlanStep(description="write", tool="write_file", arguments={"path": "app.py"}))]
        self.assertIn("optimized", strategy.build(state, {}))
        state.current_step.proposal.arguments["path"] = "requirements.txt"
        self.assertEqual(strategy.build(state, {}), "baseline")
        state.current_step.proposal.arguments["path"] = "app.py"
        state.needs_replan = True
        self.assertEqual(strategy.build(state, {}), "baseline")

    def test_prompt_is_frozen_in_run_and_survives_source_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = PromptArtifact(instructions="Original instruction", input_fields=["task"], output_field="response")
            source = root / "prompt.json"
            source.write_text(artifact.model_dump_json())
            manager = StateManager.create(root / "runs", "Goal", ModelConfig(), RunLimits(),
                                          options=RuntimeOptions(prompt_artifact=str(source)))
            source.write_text("changed")
            state = manager.recover()
            saved = PromptArtifact.load(manager.run_dir / state.options.prompt_artifact)
            self.assertIn("Original instruction", saved.render({"task": "Write code"}))
            self.assertEqual(state.goal, "Goal")


@unittest.skipUnless(importlib.util.find_spec("dspy"), "Install .[dspy] for integration tests")
class DSPyTests(unittest.TestCase):
    def setUp(self):
        import dspy
        from miniagent.integrations.dspy.lm import BackendLM, InferenceBudget
        from miniagent.integrations.dspy.program import ProgramAdapter
        self.dspy = dspy
        class Backend:
            config = ModelConfig()
            def generate(self, prompt):
                return ModelResponse(text="yes", input_tokens=10, output_tokens=2)
        self.backend = Backend()
        self.lm = BackendLM(self.backend, ModelConfig(), InferenceBudget(max_calls=20))
        self.program = ProgramAdapter(dspy.Predict("task -> response"), self.lm)

    def test_real_predict_bootstrap_evaluate_and_portable_export(self):
        from miniagent.integrations.dspy.strategies import BootstrapStrategy
        examples = [self.dspy.Example(task=task, response="yes").with_inputs("task") for task in ["A", "B"]]
        metric = lambda example, prediction, trace=None: prediction.response == example.response
        compiled = self.program.optimize(BootstrapStrategy(), examples, [], metric)
        self.assertEqual(compiled(task="C").response, "yes")
        self.assertEqual(compiled.evaluate(examples, metric).score, 100)
        artifact = compiled.export()
        self.assertEqual(len(artifact.demos), 2)
        self.assertIn("EXAMPLE", artifact.render({"task": "D"}))

    def test_copies_share_model_and_budget_without_copying_weights(self):
        clone = copy.deepcopy(self.lm)
        self.assertIs(clone.backend, self.backend)
        self.assertIs(clone.budget, self.lm.budget)
        self.assertIsNot(clone.history, self.lm.history)
        self.lm.budget.max_calls = 1
        self.assertEqual(self.lm("A"), ["yes"])
        with self.assertRaisesRegex(RuntimeError, "budget exhausted"):
            clone("B")

    def test_other_dspy_modules_can_use_another_format_adapter(self):
        from miniagent.integrations.dspy.program import ProgramAdapter
        def generate(prompt):
            return ModelResponse(text="[[ ## reasoning ## ]]\nChecked.\n[[ ## answer ## ]]\n42\n[[ ## completed ## ]]",
                                 input_tokens=10, output_tokens=20)
        self.backend.generate = generate
        adapter = ProgramAdapter(self.dspy.ChainOfThought("question -> answer"), self.lm,
                                 self.dspy.ChatAdapter(use_json_adapter_fallback=False))
        self.assertEqual(adapter(question="Six times seven?").answer, "42")
        with self.assertRaisesRegex(ValueError, "RawTextAdapter"):
            adapter.export()

    def test_callable_strategy_can_replace_the_optimizer(self):
        from miniagent.integrations.dspy.strategies import CallableStrategy
        def compile_program(program, train, validation, metric, lm):
            self.assertIs(lm, self.lm)
            return program.deepcopy()
        compiled = self.program.optimize(CallableStrategy(compile_program), [], [], lambda *args: 1.0)
        self.assertEqual(compiled(task="Another task").response, "yes")

    def test_typed_request_rejects_native_tool_authority(self):
        request = self.dspy.LMRequest.from_call(model="local", prompt="Run tool", tools=[{
            "type": "function", "function": {"name": "shell", "parameters": {"type": "object", "properties": {}}},
        }])
        with self.assertRaisesRegex(ValueError, "tool authority"):
            self.lm(request)

    def test_unsupported_options_are_not_silently_ignored(self):
        with self.assertRaisesRegex(ValueError, "top_p"):
            self.lm("A", top_p=0.5)
        self.assertEqual(self.lm.budget.calls, 0)

    def test_local_lm_serialization_restores_local_backend_without_loading_weights(self):
        from miniagent.integrations.dspy.lm import BackendLM
        from miniagent.model.transformers_model import TransformersBackend
        config = ModelConfig(model="/local/model", seed=42)
        predictor = self.dspy.Predict("task -> response")
        predictor.set_lm(BackendLM(TransformersBackend(config), config))
        state = predictor.dump_state()
        restored = self.dspy.Predict("task -> response")
        restored.load_state(state, allow_unsafe_lm_state=True)
        self.assertIsInstance(restored.lm, BackendLM)
        self.assertIsInstance(restored.lm.backend, TransformersBackend)
        self.assertEqual(restored.lm.config, config)
        self.assertIsNone(restored.lm.backend.model)

    def test_failed_backend_restores_config_and_consumes_conservative_budget(self):
        previous = self.backend.config
        with patch.object(self.backend, "generate", side_effect=RuntimeError("failed")):
            with self.assertRaisesRegex(RuntimeError, "failed"):
                self.lm("A", temperature=0.4)
        self.assertIs(self.backend.config, previous)
        self.assertEqual(self.lm.budget.calls, 1)
        self.assertGreater(self.lm.budget.tokens, 0)
