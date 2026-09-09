"""Reference output for the scripted regression fixture, not a model benchmark."""

from flask import Flask, jsonify, request

app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify(status="ok")


@app.get("/fibonacci")
def fibonacci():
    values = request.args.getlist("n")
    if len(values) != 1:
        return jsonify(error="Provide exactly one n"), 400
    raw = values[0]
    if not raw or not raw.isascii() or not raw.isdecimal():
        return jsonify(error="n must contain ASCII decimal digits"), 400
    significant = raw.lstrip("0") or "0"
    if len(significant) > 4 or int(significant) > 1000:
        return jsonify(error="n must be between 0 and 1000"), 400
    n = int(significant)
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return jsonify(n=n, value=a)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
