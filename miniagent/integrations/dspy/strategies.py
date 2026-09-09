from dataclasses import dataclass
from typing import Callable, Protocol

import dspy


class OptimizationStrategy(Protocol):
    def compile(self, program, trainset, valset, metric, lm): ...


@dataclass
class BootstrapStrategy:
    demos: int = 2

    def compile(self, program, trainset, valset, metric, lm):
        optimizer = dspy.BootstrapFewShot(metric=metric, metric_threshold=1.0, max_bootstrapped_demos=self.demos,
                                        max_labeled_demos=self.demos, max_rounds=1, max_errors=3)
        return optimizer.compile(program, trainset=trainset)


@dataclass
class GEPAStrategy:
    max_metric_calls: int = 8

    def compile(self, program, trainset, valset, metric, lm):
        def feedback_metric(example, prediction, trace=None, pred_name=None, pred_trace=None):
            value = metric(example, prediction, trace)
            if isinstance(value, dict):
                return dspy.Prediction(**value)
            return dspy.Prediction(score=float(value), feedback="Passed the executable contract" if value == 1 else "The generated code failed executable checks")
        optimizer = dspy.GEPA(metric=feedback_metric, max_metric_calls=self.max_metric_calls,
                             reflection_lm=lm, reflection_minibatch_size=1, num_threads=1,
                             use_merge=False, track_stats=True, seed=0)
        return optimizer.compile(program, trainset=trainset, valset=valset)


@dataclass
class CallableStrategy:
    """Explicit extension point for other DSPy optimizers or complete modules."""
    compiler: Callable

    def compile(self, program, trainset, valset, metric, lm):
        return self.compiler(program, trainset, valset, metric, lm)
