import importlib.util
import tempfile
import unittest

from miniagent.state.models import ModelConfig


@unittest.skipUnless(importlib.util.find_spec("transformers") and importlib.util.find_spec("torch"), "Install .[local] for real offline inference smoke test")
class TransformersTests(unittest.TestCase):
    def test_real_local_model_and_token_accounting(self):
        import torch
        from tokenizers import Tokenizer
        from tokenizers.models import WordLevel
        from tokenizers.pre_tokenizers import Whitespace
        from transformers import Phi3Config, Phi3ForCausalLM, PreTrainedTokenizerFast
        from miniagent.model.transformers_model import TransformersBackend

        torch.manual_seed(0)
        with tempfile.TemporaryDirectory() as directory:
            tokenizer = Tokenizer(WordLevel({"[UNK]": 0, "[EOS]": 1, "hello": 2, "user": 3, "assistant": 4}, unk_token="[UNK]"))
            tokenizer.pre_tokenizer = Whitespace()
            fast = PreTrainedTokenizerFast(tokenizer_object=tokenizer, unk_token="[UNK]", eos_token="[EOS]")
            fast.chat_template = "{% for message in messages %}{{ message['role'] + ' ' + message['content'] + ' ' }}{% endfor %}assistant "
            fast.save_pretrained(directory)
            config = Phi3Config(
                vocab_size=5, hidden_size=32, intermediate_size=64, num_hidden_layers=1,
                num_attention_heads=4, num_key_value_heads=2, max_position_embeddings=256,
                original_max_position_embeddings=256, bos_token_id=1, eos_token_id=1,
                pad_token_id=1,
            )
            Phi3ForCausalLM(config).save_pretrained(directory, safe_serialization=True)
            backend = TransformersBackend(ModelConfig(model=directory, device="cpu", max_new_tokens=2, max_context_tokens=128))
            response = backend.generate("hello")
            self.assertEqual(response.input_tokens, 3)
            self.assertGreaterEqual(response.output_tokens, 1)
            self.assertLessEqual(response.output_tokens, 2)
            with self.assertRaisesRegex(ValueError, "Context has"):
                backend.generate("hello " * 150)
