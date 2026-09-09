import unittest
from unittest.mock import patch

from examples.fibonacci_flask.gguf_demo import LocalLlamaBackend
from miniagent.state.models import ModelConfig


class LocalLlamaExampleTests(unittest.TestCase):
    def test_file_content_is_raw_and_reasoning_tokens_are_counted(self):
        backend = LocalLlamaBackend(ModelConfig(), 18089)
        replies = [{'input_tokens': 20}, {'choices': [{'message': {
            'content': '```java\nclass Main {}\n```', 'reasoning_content': 'Private intermediate text'}}],
            'usage': {'prompt_tokens': 20, 'completion_tokens': 80}}]
        with patch.object(backend, 'request', side_effect=replies) as request:
            response = backend.generate('Write a Java file')
        self.assertEqual(response.text, '```java\nclass Main {}\n```')
        self.assertEqual(response.output_tokens, 80)
        payload = request.call_args_list[-1].args[1]
        self.assertEqual(payload['max_tokens'], backend.config.max_new_tokens)
        self.assertNotIn('response_format', payload)
        self.assertNotIn('tools', payload)

    def test_context_overflow_rejected_before_generation(self):
        backend = LocalLlamaBackend(ModelConfig(), 18089)
        with patch.object(backend, 'request', return_value={'input_tokens': 5000}) as request:
            with self.assertRaisesRegex(ValueError, 'allowance'):
                backend.generate('Too large')
        self.assertEqual(request.call_count, 1)

    def test_native_tools_do_not_bypass_runtime(self):
        backend = LocalLlamaBackend(ModelConfig(), 18089)
        replies = [{'input_tokens': 20}, {'choices': [{'message': {'tool_calls': [{'name': 'shell'}]}}]}]
        with patch.object(backend, 'request', side_effect=replies), self.assertRaisesRegex(ValueError, 'Native tool calls'):
            backend.generate('Do work')
