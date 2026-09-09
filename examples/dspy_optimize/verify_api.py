"""Trusted contracts for training APIs; never contains a Fibonacci implementation."""
import importlib.util
import json
from pathlib import Path

contract = json.loads(Path("contract.json").read_text())
cases = contract["cases"]
passed, failures = 0, []
try:
    spec = importlib.util.spec_from_file_location("generated_app", "solution.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.app.config["TESTING"] = True
    client = module.app.test_client()
    for case in cases:
        try:
            response = client.get(case["path"], query_string=case.get("query"))
            correct = response.status_code == case["status"]
            if "json" in case:
                correct = correct and response.json == case["json"]
            else:
                correct = correct and response.is_json and isinstance(response.json.get("error"), str)
            if correct:
                passed += 1
            else:
                failures.append(f"{case!r}: got HTTP {response.status_code}, {response.get_data(as_text=True)[:100]}")
        except Exception as error:
            failures.append(f"{type(error).__name__}: {str(error)[:150]}")
except Exception as error:
    failures.append(f"{type(error).__name__}: {str(error)[:150]}")
print(json.dumps({"passed": passed, "total": len(cases), "feedback": failures[:3]}))
