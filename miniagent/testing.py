"""Small unittest runner for bounded, concrete feedback from trusted verifiers."""

import json
import re
import unittest


def run_contract(suite: unittest.TestSuite, expected_tests: int) -> bool:
    result = unittest.TestResult()
    suite.run(result)
    # Prioritize concrete errors, then assertions. Avoid pages of repeated traces.
    for test, trace in [*result.errors, *result.failures][:3]:
        lines = trace.strip().splitlines()
        start = next((i for i, line in enumerate(lines) if re.match(r"^[\w.]+(?:Error|Exception):", line)), max(0, len(lines) - 3))
        message = "\n".join(lines[start:])
        print(f"FAIL {str(test)[:120]}\n{message[:500]}")
    failed_methods = {test.id().split(" (")[0] for test, _ in [*result.errors, *result.failures, *result.skipped]}
    summary = {"tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors)}
    print(json.dumps(summary))
    print(json.dumps({"miniagent_verification": {**summary,
                      "tests_passed": max(0, result.testsRun - len(failed_methods) - len(result.expectedFailures))}}))
    return result.wasSuccessful() and result.testsRun == expected_tests and not result.skipped and not result.expectedFailures
