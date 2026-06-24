"""HuggingFace transformers in-process persona backend.

For small models (Qwen3-1.7B class) that can be loaded into the API process.
For anything bigger, use vllm_endpoint instead — a single Python process
cannot serve many concurrent inferences for a 7B+ model efficiently.

backend_config contract:
    {
      "model_id":      "Qwen/Qwen3-1.7B-Instruct",   # required (HF hub id or local path)
      "lora_adapter":  "buddle/poet-v2",             # optional, PEFT adapter
      "dtype":         "bfloat16",                   # optional: float16|bfloat16|float32
      "device":        "auto",                       # optional: cuda|cpu|auto
      "temperature":   0.7,
      "max_new_tokens": 512
    }

Loading is lazy and per-(model_id, lora_adapter) cached in a module-level dict
so identical models share a single in-memory instance. transformers + torch
are imported only when an actual local_hf model is invoked — avoiding the
import cost during tests that only use stubs.
"""

from __future__ import annotations

import asyncio
from typing import Any

from buddle.ai.interfaces import (
    DialogueTurn,
    PersonaInterpretation,
    PersonaReply,
)
from buddle.ai.personas.prompts import (
    build_dialogue_messages,
    build_interpret_messages,
)
from buddle.ai.personas.vllm_endpoint import PersonaBackendError  # reuse exception
from buddle.core.logging import get_logger

log = get_logger(__name__)

# Process-wide cache of loaded (tokenizer, model) tuples keyed by config.
_loaded: dict[str, tuple[Any, Any]] = {}
_load_lock = asyncio.Lock()


def _cache_key(config: dict[str, Any]) -> str:
    return f"{config.get('model_id')}::{config.get('lora_adapter') or ''}"


async def _ensure_loaded(config: dict[str, Any]) -> tuple[Any, Any]:
    """Return (tokenizer, model). Load on first use; cache for subsequent calls."""
    key = _cache_key(config)
    if key in _loaded:
        return _loaded[key]

    async with _load_lock:
        if key in _loaded:
            return _loaded[key]

        try:
            import torch
            from transformers import (
                AutoModelForCausalLM,
                AutoTokenizer,
            )
        except ImportError as e:
            raise PersonaBackendError(
                "local_hf backend requires 'transformers' and 'torch'. "
                "Install them, or use 'vllm_endpoint' instead."
            ) from e

        model_id = config["model_id"]
        dtype_name = str(config.get("dtype", "bfloat16")).lower()
        dtype = {
            "float16": torch.float16,
            "bfloat16": torch.bfloat16,
            "float32": torch.float32,
        }.get(dtype_name, torch.bfloat16)

        device_map = config.get("device", "auto")

        log.info("persona.local_hf.loading", model_id=model_id, dtype=dtype_name)
        tokenizer = AutoTokenizer.from_pretrained(model_id)
        model = AutoModelForCausalLM.from_pretrained(
            model_id, torch_dtype=dtype, device_map=device_map
        )

        lora = config.get("lora_adapter")
        if lora:
            try:
                from peft import PeftModel
            except ImportError as e:
                raise PersonaBackendError("lora_adapter requires the 'peft' package.") from e
            model = PeftModel.from_pretrained(model, lora)
            log.info("persona.local_hf.lora_loaded", lora_adapter=lora)

        model.eval()
        _loaded[key] = (tokenizer, model)
        return _loaded[key]


def _generate_sync(
    tokenizer: Any,
    model: Any,
    messages: list[dict[str, str]],
    *,
    temperature: float,
    max_new_tokens: int,
) -> str:
    """Blocking inference. Caller wraps in asyncio.to_thread()."""
    import torch

    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            do_sample=temperature > 0,
            pad_token_id=tokenizer.eos_token_id,
        )

    # Strip the prompt portion
    generated = output_ids[0][inputs["input_ids"].shape[1] :]
    text = tokenizer.decode(generated, skip_special_tokens=True)
    return str(text)


class LocalHfPersona:
    def __init__(self, *, model_key: str, system_prompt: str | None, config: dict[str, Any] | None):
        self._model_key = model_key
        self._system_prompt = system_prompt
        self._config = config or {}
        if not self._config.get("model_id"):
            raise PersonaBackendError(
                f"backend_config.model_id is required for local_hf model '{model_key}'"
            )

    async def interpret(
        self,
        *,
        persona_name: str,
        model_key: str,
        content_raw: str,
    ) -> PersonaInterpretation:
        messages = build_interpret_messages(
            persona_name=persona_name,
            model_system_prompt=self._system_prompt,
            content_raw=content_raw,
        )
        text = await self._chat(messages)
        return PersonaInterpretation(
            content_transformed=text.strip(),
            metadata={
                "backend": "local_hf",
                "model_key": model_key,
                "model_id": str(self._config["model_id"]),
            },
        )

    async def respond_in_dialogue(
        self,
        *,
        persona_name: str,
        model_key: str,
        history: list[DialogueTurn],
        user_message: str,
        recalled_memories: list[str] | None = None,
        conversation_guidance: str = "",
        user_context: object = None,
    ) -> PersonaReply:
        messages = build_dialogue_messages(
            persona_name=persona_name,
            model_system_prompt=self._system_prompt,
            history=history,
            user_message=user_message,
            recalled_memories=recalled_memories,
            conversation_guidance=conversation_guidance,
            user_context=user_context,  # type: ignore[arg-type]
        )
        text = await self._chat(messages)
        return PersonaReply(
            content=text.strip(),
            metadata={
                "backend": "local_hf",
                "model_key": model_key,
                "model_id": str(self._config["model_id"]),
            },
        )

    async def _chat(self, messages: list[dict[str, str]]) -> str:
        tokenizer, model = await _ensure_loaded(self._config)
        try:
            return await asyncio.to_thread(
                _generate_sync,
                tokenizer,
                model,
                messages,
                temperature=float(self._config.get("temperature", 0.7)),
                max_new_tokens=int(self._config.get("max_new_tokens", 512)),
            )
        except Exception as e:
            log.exception("persona.local_hf.generate_failed", model_key=self._model_key)
            raise PersonaBackendError(f"local_hf generation failed: {e}") from e
