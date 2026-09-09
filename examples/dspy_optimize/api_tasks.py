import dspy


def training_api(route: str, expression: str, operation):
    task = (f"Write app.py: a Flask instance app. GET /health returns {{\"status\":\"ok\"}}. "
            f"GET /{route}?value=5 returns JSON {{\"input\":5,\"result\":{operation(5)}}}. "
            f"Compute {expression} for every integer value from 0 through 999. "
            "The query parameter value must occur exactly once and contain only ASCII digits. "
            "Allow leading zeros. Invalid, missing, repeated or out-of-range values return JSON error and HTTP 400. "
            "Bound work even for very long inputs. Do not start a server during import. Return one Python code fence.")
    code = f'''from flask import Flask, request, jsonify

app = Flask(__name__)

def parse_value(values):
    if len(values) != 1:
        raise ValueError("provide value once")
    raw = values[0]
    if not raw or not raw.isascii() or not raw.isdigit():
        raise ValueError("ASCII digits required")
    digits = raw.lstrip("0") or "0"
    if len(digits) > 3:
        raise ValueError("out of range")
    return int(digits)

@app.get("/health")
def health():
    return jsonify(status="ok")

@app.get("/{route}")
def endpoint():
    try:
        value = parse_value(request.args.getlist("value"))
    except ValueError as error:
        return jsonify(error=str(error)), 400
    return jsonify(input=value, result={expression})
'''
    cases = [{"path": "/health", "status": 200, "json": {"status": "ok"}}]
    cases += [{"path": f"/{route}", "query": {"value": value}, "status": 200,
               "json": {"input": int(value), "result": operation(int(value))}} for value in ["0", "1", "5", "0999", "000005"]]
    cases += [{"path": f"/{route}", "query": query, "status": 400} for query in [
        {}, {"value": ""}, {"value": "-1"}, {"value": "+1"}, {"value": "1000"}, {"value": "١"}, [("value", "1"), ("value", "2")],
    ]]
    return dspy.Example(task=task, response="```python\n" + code + "```", name=route,
                        cases=cases, verifier="verify_api.py").with_inputs("task")


def api_training_set():
    return [training_api("square", "value * value", lambda n: n * n),
            training_api("double", "value * 2", lambda n: n * 2)]
