"""Buscar una foto con licencia libre de un objeto real (ADR-048, fase 2)."""
from __future__ import annotations

from typing import Protocol

from src.domain.services.visuals import LicensedImage


class ImageFinder(Protocol):
    async def find(self, query: str) -> LicensedImage | None:
        """Una foto libre, atribuible y moderada del objeto; None si no hay o algo falla."""
        ...
