"""In-process HuggingFace ethics/moderation classifier.

Loads a text-classification model (e.g. a fine-tuned KoBERT/DeBERTa toxicity
model) once and runs it in a worker thread. Label -> severity mapping is
provided via config so different models with different label schemes can be
adapted without code changes.

config:
    {
      "model_id": "smilegate-ai/kor_unsmile",          # example
      "device": "cpu",
      "label_severity": {                               # model label -> severity
        "clean": "none",
        "악플/욕설": "mid",
        "혐오": "high"
      },
      "score_threshold": 0.5
    }

transformers/torch are imported lazily so stub-only environments don't pay
the cost.
"""

from __future__ import annotations

import asyncio
from typing import Any

from buddle.ai.ethics.base import EthicsAssessment, EthicsError, EthicsSeverity
from buddle.core.logging import get_logger

log = get_logger(__name__)

_pipe_cache: dict[str, Any] = {}
_load_lock = asyncio.Lock()


async def _ensure_pipeline(config: dict[str, Any]) -> Any:
    model_id = config.get("model_id")
    if not model_id:
        raise EthicsError("local_hf ethics config requires 'model_id'")
    if model_id in _pipe_cache:
        return _pipe_cache[model_id]

    async with _load_lock:
        if model_id in _pipe_cache:
            return _pipe_cache[model_id]
        try:
            from transformers import pipeline
        except ImportError as e:
            raise EthicsError("local_hf ethics backend requires 'transformers' (+ torch).") from e

        device = 0 if config.get("device") == "cuda" else -1
        log.info("ethics.local_hf.loading", model_id=model_id)
        pipe = pipeline(
            "text-classification",
            model=model_id,
            device=device,
            top_k=None,  # return all label scores
        )
        _pipe_cache[model_id] = pipe
        return pipe


def _classify_sync(pipe: Any, text: str) -> list[dict[str, Any]]:
    out = pipe(text, truncation=True)
    # transformers may return list[list[dict]] when top_k=None
    if out and isinstance(out[0], list):
        return out[0]
    return out


class LocalHfEthicsClassifier:
    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or {}
        self._label_severity: dict[str, EthicsSeverity] = {
            label: EthicsSeverity(sev)
            for label, sev in self._config.get("label_severity", {}).items()
        }
        self._threshold = float(self._config.get("score_threshold", 0.5))

    async def assess(self, text: str) -> EthicsAssessment:
        pipe = await _ensure_pipeline(self._config)
        try:
            scores = await asyncio.to_thread(_classify_sync, pipe, text)
        except Exception as e:
            log.exception("ethics.local_hf.classify_failed")
            raise EthicsError(f"local_hf classification failed: {e}") from e

        worst = EthicsSeverity.NONE
        worst_rank = 0
        fired: list[str] = []
        max_score = 0.0
        rank = {
            EthicsSeverity.NONE: 0,
            EthicsSeverity.LOW: 1,
            EthicsSeverity.MID: 2,
            EthicsSeverity.HIGH: 3,
        }

        for item in scores:
            label = item.get("label", "")
            score = float(item.get("score", 0.0))
            severity = self._label_severity.get(label, EthicsSeverity.NONE)
            if severity == EthicsSeverity.NONE or score < self._threshold:
                continue
            fired.append(label)
            max_score = max(max_score, score)
            if rank[severity] > worst_rank:
                worst_rank = rank[severity]
                worst = severity

        return EthicsAssessment(
            severity=worst,
            score=max_score,
            categories=fired,
            reason=(f"model labels: {', '.join(fired)}" if fired else None),
            metadata={"classifier": "local_hf", "model_id": str(self._config.get("model_id"))},
        )
