"""Run the unchanged coding workflow against an explicitly started local llama-server."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import tomllib
from urllib.request import ProxyHandler, Request, build_opener

if __package__:
    from .demo import create_run
else:
    from demo import create_run
from miniagent.model.base import ModelResponse
from miniagent.runtime import Runtime
from miniagent.state.manager import StateManager
from miniagent.state.models import ModelConfig, RunLimits, RuntimeOptions


class LocalLlamaBackend:
    """Example-only ModelBackend adapter; no API key, remote service or new dependency."""
    def __init__(self, config: ModelConfig, port: int):
        self.config = config
        self.url = f"http://127.0.0.1:{port}"
        self.http = build_opener(ProxyHandler({}))

    def request(self, route: str, payload: dict | None = None) -> dict:
        request = Request(self.url + route, json.dumps(payload).encode() if payload is not None else None,
                          {"Content-Type": "application/json"})
        with self.http.open(request, timeout=self.config.max_generation_seconds) as response:
            data = response.read(1000001)
        if len(data) > 1000000:
            raise ValueError("Local model response exceeded the byte limit")
        return json.loads(data)

    def generate(self, prompt: str) -> ModelResponse:
        seed = (self.config.seed + int.from_bytes(hashlib.sha256(prompt.encode()).digest()[:4], "big")) % 2147483648
        payload = {"messages": [{"role": "user", "content": prompt}], "stream": False,
                   "temperature": self.config.temperature, "seed": seed, "top_p": 0.95,
                   "max_tokens": self.config.max_new_tokens,
                   "chat_template_kwargs": {"reasoning_effort": "high"}}
        count = self.request('/v1/chat/completions/input_tokens', payload)['input_tokens']
        if count > self.config.max_context_tokens:
            raise ValueError(f"Prompt has {count} tokens; allowance is {self.config.max_context_tokens}")
        result = self.request('/v1/chat/completions', payload)
        message = result['choices'][0]['message']
        if message.get('tool_calls'):
            raise ValueError("Native tool calls are not enabled in this file-generation example")
        return ModelResponse(text=message.get('content') or '', input_tokens=result['usage']['prompt_tokens'],
                             output_tokens=result['usage']['completion_tokens'])


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--model', required=True, help='Existing GGUF model path; server must load exactly this model')
    cli.add_argument('--revision', required=True, help='Model provenance revision or SHA-256')
    cli.add_argument('--port', type=int, default=18089)
    cli.add_argument('--runs-dir', type=Path, default=Path('runs'))
    cli.add_argument('--resume', type=Path)
    cli.add_argument('--limits-config', type=Path, default=Path('examples/fibonacci_flask/long_run.toml'))
    cli.add_argument('--max-new-tokens', type=int, default=4096)
    cli.add_argument('--temperature', type=float, default=0.4)
    args = cli.parse_args()
    if not 1 <= args.port <= 65535:
        cli.error('Invalid local port')
    if args.resume:
        manager = StateManager(args.resume)
    else:
        config = ModelConfig(model=str(Path(args.model).resolve()), revision=args.revision,
                             device='cuda', max_new_tokens=args.max_new_tokens, max_context_tokens=4096,
                             max_generation_seconds=180.0, temperature=args.temperature)
        limits = RunLimits.model_validate(tomllib.loads(args.limits_config.read_text())['limits'])
        options = RuntimeOptions(file_output_format='fenced', planning_strategy='files', execute_plan=True,
                                 repair_strategy='rewrite', repair_paths=['app.py'], keep_best=True)
        manager = create_run(args.runs_dir, config, limits, options)
    print(f'Run: {manager.run_dir}', flush=True)
    backend = LocalLlamaBackend(manager.load().model_config_saved, args.port)
    properties = backend.request('/props')
    if Path(properties['model_path']).resolve() != Path(backend.config.model).resolve():
        raise ValueError('The local server has loaded a different model')
    state = Runtime(manager, backend).run()
    report = {"backend": "local llama.cpp server", "run_id": state.run_id, "status": state.status,
              "model": state.model_config_saved.model_dump(), "runtime_options": state.options.model_dump(),
              "limits": state.limits.model_dump(), "iterations": state.iteration, "tool_calls": state.tool_calls,
              "replans": state.replans, "tokens": state.token_budget_used, "metrics": state.metrics.model_dump(),
              "best_tests_passed": state.best_attempt.passed if state.best_attempt else None,
              "seconds": round((state.finished_at or time.time()) - state.started_at, 2), "reason": state.feedback}
    (manager.run_dir / 'experiment.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if state.status == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
