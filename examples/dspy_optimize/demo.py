"""Optimize with the same local small model; score separate executable test tasks."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

import dspy

from miniagent.integrations.dspy.lm import BackendLM, InferenceBudget
from miniagent.integrations.dspy.strategies import BootstrapStrategy, GEPAStrategy
from miniagent.integrations.dspy.program import ProgramAdapter
from miniagent.model.transformers_model import TransformersBackend
from miniagent.parsing.file_parser import parse_file_content
from miniagent.parsing.json_parser import ParseError
from miniagent.state.models import ModelConfig, ToolPolicy
from miniagent.tools.base import ToolContext
from miniagent.tools.shell import run_command

HERE = Path(__file__).resolve().parent


def example(name, requirement, code, cases):
    return dspy.Example(task=f"Write the Python function {name}. {requirement} Return only the complete function in one python code fence.",
                        response=f"```python\n{code}\n```", name=name,
                        cases=[{"args": args, "expected": expected} for args, expected in cases]).with_inputs("task")


def datasets():
    def fib_pair(n):
        if n == 0:
            return 0, 1
        a, b = fib_pair(n // 2)
        c, d = a * (2 * b - a), a * a + b * b
        return (d, c + d) if n % 2 else (c, d)
    train = [
        example("factorial(n)", "Return n factorial for nonnegative integers using a loop, not recursion.",
                "def factorial(n):\n    result = 1\n    for i in range(2, n + 1):\n        result *= i\n    return result", [([0], 1), ([1], 1), ([5], 120)]),
        example("count_positive(values)", "Count values strictly greater than zero.",
                "def count_positive(values):\n    count = 0\n    for value in values:\n        if value > 0:\n            count += 1\n    return count", [([[]], 0), ([[-1, 0, 2, 3]], 2)]),
        example("parse_decimal(text)", "Return an integer only for nonempty strings containing ASCII digits; otherwise return None.",
                "def parse_decimal(text):\n    if not isinstance(text, str) or not text or not text.isascii() or not text.isdigit():\n        return None\n    return int(text)",
                [(["12"], 12), (["١"], None), (["+1"], None), ([None], None)]),
    ]
    validation = [example("parse_small_int(text)", "Accept ASCII digit strings with numeric value 0 through 99, allowing leading zeros. Return the integer, or None for invalid input.", "",
                          [(["005"], 5), (["100"], None), (["١"], None), ([None], None), (["+1"], None)])]
    test = [
        example("square(x)", "Return x squared.", "", [([0], 0), ([-3], 9), ([4], 16)]),
        example("sum_list(values)", "Return the sum; an empty list returns zero.", "", [([[]], 0), ([[1, 2, 3]], 6), ([[-2, 1]], -1)]),
        example("fibonacci(n)", "Return F(n), with F(0)=0 and F(1)=1. Support n=1000 using linear time, without recursion.", "",
                [([0], 0), ([1], 1), ([2], 1), ([10], 55), ([50], 12586269025), ([1000], fib_pair(1000)[0])]),
    ]
    return train, validation, test


def assess(example, prediction, trace=None):
    try:
        source = parse_file_content(prediction.response, "solution.py").arguments["content"]
    except (ParseError, AttributeError) as error:
        return {"score": 0.0, "feedback": f"Python file could not be parsed: {error}"}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "solution.py").write_text(source)
        (root / "contract.json").write_text(json.dumps({"name": example.name.split("(")[0], "cases": example.cases}))
        result = run_command([sys.executable, str(HERE / example.get("verifier", "verify_function.py"))],
                             ToolContext(root, output_limit=2000, policy=ToolPolicy(command_timeout_seconds=3.0)))
        try:
            report = json.loads(result.output.splitlines()[-1])
            if not result.success:
                raise ValueError(result.error)
            return {"score": report["passed"] / report["total"], "feedback": str(report["feedback"]) or "Passed"}
        except (ValueError, KeyError, IndexError):
            return {"score": 0.0, "feedback": (result.error or result.output)[:500]}


def metric(example, prediction, trace=None):
    return assess(example, prediction)["score"]


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--strategy", choices=["bootstrap", "gepa"], default="bootstrap")
    cli.add_argument("--model", default="Qwen/Qwen2.5-Coder-0.5B-Instruct")
    cli.add_argument("--revision", default="ea3f2471cf1b1f0db85067f1ef93848e38e88c25")
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--max-metric-calls", type=int, default=8)
    cli.add_argument("--api-examples", action="store_true", help="Include labelled square/double Flask APIs as domain demonstrations")
    args = cli.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    config = ModelConfig(model=args.model, revision=args.revision, max_new_tokens=1024, max_context_tokens=8192, temperature=0.4)
    lm = BackendLM(TransformersBackend(config), config, InferenceBudget(max_calls=60, max_tokens=300000), args.output / "calls.jsonl")
    train, validation, test = datasets()
    if args.api_examples:
        from api_tasks import api_training_set
        train = [*api_training_set(), train[0]]
        for example in train:
            report = assess(example, dspy.Prediction(response=example.response))
            if report["score"] != 1.0:
                raise ValueError(f"Invalid training label for {example.name}: {report}")
    signature = dspy.Signature("task -> response", instructions="Write correct Python code for the requested function. Return one python code fence.")
    program = dspy.Predict(signature)
    strategy = BootstrapStrategy(demos=3 if args.api_examples else 2) if args.strategy == "bootstrap" else GEPAStrategy(args.max_metric_calls)
    started = time.monotonic()
    adapter = ProgramAdapter(program, lm)
    baseline = adapter.evaluate(test, metric)
    compiled = adapter.optimize(strategy, train, validation, assess if args.strategy == "gepa" else metric)
    optimized = compiled.evaluate(test, metric)
    artifact = compiled.export()
    (args.output / "prompt.json").write_text(artifact.model_dump_json(indent=2) + "\n")
    results = {"strategy": args.strategy, "model": config.model_dump(), "dspy_version": dspy.__version__,
               "api_examples": args.api_examples, "max_metric_calls": args.max_metric_calls if args.strategy == "gepa" else None,
               "train": [e.name for e in train], "validation": [e.name for e in validation], "test": [e.name for e in test],
               "baseline_score": baseline.score, "optimized_score": optimized.score,
               "baseline_tasks": [score for _, _, score in baseline.results],
               "optimized_tasks": [score for _, _, score in optimized.results],
               "lm_calls": lm.budget.calls, "tokens": lm.budget.tokens, "seconds": round(time.monotonic() - started, 2),
               "demos": len(artifact.demos), "instructions": artifact.instructions}
    (args.output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
