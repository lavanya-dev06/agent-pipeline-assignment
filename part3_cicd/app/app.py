"""Minimal Flask app — stands in for 'the small provided repo' referenced
in the brief so the CI/CD pipeline in Part 3 has something real to run
tests/lint against and deploy."""

from flask import Flask, jsonify

app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify(status="ok")


@app.get("/api/greeting/<name>")
def greeting(name: str):
    if not name.strip():
        return jsonify(error="name cannot be empty"), 400
    return jsonify(message=f"Hello, {name}!")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
