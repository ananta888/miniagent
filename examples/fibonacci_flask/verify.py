"""Trusted acceptance tests, executed outside the agent's writable workspace."""

import importlib.util
import json
from pathlib import Path
import sys
import unittest


def fibonacci_oracle(n: int) -> int:
    def pair(index):
        if index == 0:
            return 0, 1
        a, b = pair(index // 2)
        c, d = a * (2 * b - a), a * a + b * b
        return (d, c + d) if index % 2 else (c, d)
    return pair(n)[0]


class FibonacciContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path.cwd() / "app.py"
        spec = importlib.util.spec_from_file_location("generated_fibonacci_app", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.app.config.update(TESTING=True)
        cls.client = module.app.test_client()

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"status": "ok"})

    def test_known_values(self):
        for n, value in [(0, 0), (1, 1), (2, 1), (3, 2), (10, 55), (50, 12586269025)]:
            with self.subTest(n=n):
                response = self.client.get("/fibonacci", query_string={"n": str(n)})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json, {"n": n, "value": value})

    def test_large_index(self):
        response = self.client.get("/fibonacci?n=1000")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"n": 1000, "value": fibonacci_oracle(1000)})

    def assert_bad_request(self, query):
        response = self.client.get("/fibonacci", query_string=query)
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.is_json)
        self.assertIsInstance(response.json.get("error"), str)
        self.assertTrue(response.json["error"])

    def test_missing(self):
        self.assert_bad_request({})

    def test_invalid_values(self):
        for value in ["", "-1", "1001", "1.5", "abc", "+1", " 1", "1 ", "1e2", "١", "１"]:
            with self.subTest(value=value):
                self.assert_bad_request({"n": value})

    def test_repeated_argument(self):
        self.assert_bad_request([("n", "1"), ("n", "2")])

    def test_huge_input(self):
        self.assert_bad_request({"n": "9" * 5000})

    def test_leading_zeros(self):
        for value, n in [("0010", 10), ("0000010", 10), ("0" * 5000, 0)]:
            with self.subTest(value=value[:20]):
                response = self.client.get("/fibonacci", query_string={"n": value})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json, {"n": n, "value": fibonacci_oracle(n)})

    def test_unknown_route(self):
        self.assertEqual(self.client.get("/unknown").status_code, 404)

    def test_post_not_allowed(self):
        self.assertEqual(self.client.post("/fibonacci?n=10").status_code, 405)

    def test_independent_requests(self):
        for n in [*range(1001), 10, 0, 5, 1, 10]:
            response = self.client.get(f"/fibonacci?n={n}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json, {"n": n, "value": fibonacci_oracle(n)})

    def test_requirements(self):
        text = Path("requirements.txt").read_text().strip().lower().replace(" ", "")
        self.assertEqual(text, "flask>=3.1,<4")


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(FibonacciContract)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({"tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors)}))
    raise SystemExit(0 if result.wasSuccessful() and result.testsRun == 12 else 1)
