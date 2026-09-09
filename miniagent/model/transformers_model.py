from miniagent.model.base import ModelResponse
from miniagent.state.models import ModelConfig


class TransformersBackend:
    """Lazy imports keep the runtime and its tests independent of PyTorch."""

    def __init__(self, config: ModelConfig):
        self.config = config
        self.model = None

    def _load(self) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        config = self.config
        self.torch = torch
        options = {
            "revision": config.revision,
            "local_files_only": config.local_files_only,
            "trust_remote_code": False,
        }
        self.tokenizer = AutoTokenizer.from_pretrained(config.model, **options)
        device = config.device
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = AutoModelForCausalLM.from_pretrained(
            config.model,
            **options,
            device_map=device,
            dtype="auto" if device == "cuda" else torch.float32,
            attn_implementation="eager",
            use_safetensors=True,
        ).eval()

    def generate(self, prompt: str) -> ModelResponse:
        if self.model is None:
            self._load()
        inputs = self.tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}],
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
            return_dict=True,
        ).to(self.model.device)
        # Some generic tokenizers emit segment IDs; Phi-3 does not accept them.
        inputs.pop("token_type_ids", None)
        count = inputs["input_ids"].shape[-1]
        if count > self.config.max_context_tokens:
            raise ValueError(f"Context has {count} tokens; limit is {self.config.max_context_tokens}")
        window = getattr(self.model.config, "max_position_embeddings", None)
        if window and count + self.config.max_new_tokens > window:
            raise ValueError("Prompt and output allowance exceed the model context window")
        sampling = self.config.temperature > 0
        kwargs = {"temperature": self.config.temperature} if sampling else {"temperature": 1.0, "top_p": 1.0, "top_k": 50}
        with self.torch.inference_mode():
            output = self.model.generate(
                **inputs,
                max_new_tokens=self.config.max_new_tokens,
                max_time=self.config.max_generation_seconds,
                do_sample=sampling,
                pad_token_id=self.tokenizer.eos_token_id,
                **kwargs,
            )
        generated = output[0, count:]
        return ModelResponse(
            text=self.tokenizer.decode(generated, skip_special_tokens=True),
            input_tokens=count,
            output_tokens=len(generated),
        )
