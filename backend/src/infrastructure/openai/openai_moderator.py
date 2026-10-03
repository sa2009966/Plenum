"""Moderador con la API de moderación de OpenAI (ADR-036). Es gratuita y tarda ~300 ms."""
from __future__ import annotations

from typing import Mapping

import httpx

from src.domain.ports.content_moderator import ModerationUnavailable

_URL = "https://api.openai.com/v1/moderations"
#: Corto a propósito: va antes de cada turno del chat. Si tarda, se deja pasar.
_TIMEOUT_S = 4.0


class OpenAIModerator:
    def __init__(
        self,
        api_key: str,
        model: str = "omni-moderation-latest",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._client = http_client

    async def scores(self, text: str) -> Mapping[str, float]:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=_TIMEOUT_S)
        try:
            r = await self._client.post(
                _URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": self._model, "input": text},
            )
            r.raise_for_status()
            crudo = r.json()["results"][0]["category_scores"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise ModerationUnavailable(type(exc).__name__) from exc
        return {k: float(v or 0.0) for k, v in crudo.items()}
