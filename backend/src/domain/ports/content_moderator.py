"""Puerto del moderador de contenido (ADR-036): mide, no decide."""
from __future__ import annotations

from typing import Mapping, Protocol


class ModerationUnavailable(Exception):
    """El proveedor no respondió. Quien llama decide qué hacer (hoy: dejar pasar)."""


class ContentModerator(Protocol):
    async def scores(self, text: str) -> Mapping[str, float]:
        """Puntaje 0-1 por categoría ("illicit", "self-harm/intent", …).

        Lanza ModerationUnavailable si no puede medir.
        """
        ...
