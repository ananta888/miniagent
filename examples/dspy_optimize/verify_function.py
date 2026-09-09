"""Trusted verifier for small, local function-generation experiments."""
import ast
import json
from pathlib import Path

contract = json.loads(Path("contract.json").read_text())
source = Path("solution.py").read_text()
try:
    tree = ast.parse(source)
    if any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(tree)):
        raise ValueError("These pure-function tasks need no imports")
    namespace = {}
    exec(compile(tree, "solution.py", "exec"), namespace)
    function = namespace[contract["name"]]
    passed = 0
    failures = []
    for case in contract["cases"]:
        try:
            actual = function(*case["args"])
            expected = case["expected"]
            if actual == expected and type(actual) is type(expected):
                passed += 1
            else:
                failures.append(f"args={case['args']!r}: expected {expected!r}, got {actual!r}")
        except Exception as error:
            failures.append(f"args={case['args']!r}: {type(error).__name__}: {error}")
    print(json.dumps({"passed": passed, "total": len(contract["cases"]), "feedback": failures[:3]}))
except Exception as error:
    print(json.dumps({"passed": 0, "total": len(contract["cases"]), "feedback": [f"{type(error).__name__}: {str(error)[:300]}"]}))
