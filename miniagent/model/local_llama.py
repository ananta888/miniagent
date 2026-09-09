"""Shared local llama-server adapter for the optional GGUF examples."""
import hashlib
import json
from urllib.request import ProxyHandler, Request, build_opener

from miniagent.model.base import ModelResponse
from miniagent.state.models import ModelConfig


class LocalLlamaBackend:
    """Optional local ModelBackend adapter; no API key, remote service or new dependency."""
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
            raise ValueError("Native tool calls are not enabled in this adapter")
        return ModelResponse(text=message.get('content') or '', input_tokens=result['usage']['prompt_tokens'],
                             output_tokens=result['usage']['completion_tokens'])

