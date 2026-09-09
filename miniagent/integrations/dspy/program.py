from dataclasses import dataclass, field

import dspy

from miniagent.integrations.dspy.adapters import RawTextAdapter, export_prompt
from miniagent.integrations.dspy.lm import BackendLM
from miniagent.integrations.dspy.strategies import OptimizationStrategy


@dataclass
class ProgramAdapter:
    """Use ordinary DSPy modules through an explicit LM/format/optimizer boundary."""
    program: dspy.Module
    lm: BackendLM
    adapter: dspy.Adapter = field(default_factory=RawTextAdapter)

    def __call__(self, **inputs):
        with dspy.context(lm=self.lm, adapter=self.adapter, num_threads=1):
            return self.program(**inputs)

    def evaluate(self, dataset, metric):
        with dspy.context(lm=self.lm, adapter=self.adapter, num_threads=1):
            return dspy.Evaluate(devset=dataset, metric=metric, num_threads=1, max_errors=3)(self.program)

    def optimize(self, strategy: OptimizationStrategy, trainset, valset, metric):
        with dspy.context(lm=self.lm, adapter=self.adapter, num_threads=1):
            compiled = strategy.compile(self.program, trainset, valset, metric, self.lm)
        return ProgramAdapter(compiled, self.lm, self.adapter)

    def export(self, predictor_name: str | None = None):
        if not isinstance(self.adapter, RawTextAdapter):
            raise ValueError("Portable prompt export requires RawTextAdapter; other modules retain their DSPy adapter")
        predictors = dict(self.program.named_predictors())
        if predictor_name is None:
            if len(predictors) != 1:
                raise ValueError("Select a predictor explicitly when exporting a multi-predictor program")
            predictor = next(iter(predictors.values()))
        else:
            predictor = predictors[predictor_name]
        return export_prompt(predictor.signature, predictor.demos)
