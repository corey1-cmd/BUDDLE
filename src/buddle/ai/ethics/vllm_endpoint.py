"""Remote ethics/moderation classifier.

Calls an HTTP moderation endpoint and maps its response to an
EthicsAssessment. Designed for an OpenAI-moderations-style contract:

    POST {endpoint_url}/moderations  { "input": "<text>" }
    -> { "results": [ { "flagged": bool,
                        "categories": {cat: bool},
                        "category_scores": {cat: float} } ] }

config:
    {
      "endpoint_url": "https://moderate.internal/v1",  # required
      "api_key": "...",                                # optional
      "timeout_s": 15,
      "category_severity": {                            # optional overrides
        "self-harm": "high", "violence": "high",
        "harassment": "mid", "spam": "low"
      }
    }

If the endpoint shape differs, adapt _parse(). On failure raises EthicsError.
"""

from __future__ import annotations

from typing import Any

import httpx

from buddle.ai.ethics.base import EthicsAssessment, EthicsError, EthicsSeverity
from buddle.core.logging import get_logger

log = get_logger(__name__)

_DEFAULT_CATEGORY_SEVERITY: dict[str, EthicsSeverity] = {
    "self-harm": EthicsSeverity.HIGH,
    "self_harm": EthicsSeverity.HIGH,
    "violence": EthicsSeverity.HIGH,
    "sexual/minors": EthicsSeverity.HIGH,
    "hate": EthicsSeverity.MID,
    "harassment": EthicsSeverity.MID,
    "spam": EthicsSeverity.LOW,
}

_RANK = {
    EthicsSeverity.NONE: 0,
    EthicsSeverity.LOW: 1,
    EthicsSeverity.MID: 2,
    EthicsSeverity.HIGH: 3,
}


class VllmEthicsClassifier:
    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or {}
        if not self._config.get("endpoint_url"):
            raise EthicsError("ethics backend_config.endpoint_url is required")
        overrides = {
            k: EthicsSeverity(v) for k, v in self._config.get("category_severity", {}).items()
        }
        self._category_severity = {**_DEFAULT_CATEGORY_SEVERITY, **overrides}

    async def assess(self, text: str) -> EthicsAssessment:
        endpoint = str(self._config["endpoint_url"]).rstrip("/")
        url = f"{endpoint}/moderations"
        headers = {"Content-Type": "application/json"}
        api_key = self._config.get("api_key")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        timeout_s = float(self._config.get("timeout_s", 15))

        last_exc: Exception | None = None
        for attempt in (1, 2):
            try:
                async with httpx.AsyncClient(timeout=timeout_s) as client:
                    resp = await client.post(url, json={"input": text}, headers=headers)
                if resp.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"upstream {resp.status_code}", request=resp.request, response=resp
                    )
                resp.raise_for_status()
                return self._parse(resp.json())
            except (httpx.HTTPError, KeyError, ValueError) as e:
                last_exc = e
                log.warning("ethics.vllm.attempt_failed", attempt=attempt, error=str(e))

        raise EthicsError(f"vllm ethics failed after retries: {last_exc}") from last_exc

    def _parse(self, data: dict[str, Any]) -> EthicsAssessment:
        result = data["results"][0]
        categories: dict[str, bool] = result.get("categories", {})
        scores: dict[str, float] = result.get("category_scores", {})

        fired: list[str] = []
        worst = EthicsSeverity.NONE
        worst_rank = 0
        max_score = 0.0

        for cat, flagged in categories.items():
            if not flagged:
                continue
            fired.append(cat)
            max_score = max(max_score, float(scores.get(cat, 0.0)))
            severity = self._category_severity.get(cat, EthicsSeverity.MID)
            if _RANK[severity] > worst_rank:
                worst_rank = _RANK[severity]
                worst = severity

        return EthicsAssessment(
            severity=worst,
            score=max_score,
            categories=fired,
            reason=(f"moderation categories: {', '.join(fired)}" if fired else None),
            metadata={"classifier": "vllm_endpoint"},
        )
