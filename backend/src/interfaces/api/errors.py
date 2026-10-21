"""Errores con `reason` estable al nivel superior: `{"detail": "...", "reason": "..."}`.

`HTTPException(detail=dict)` anidaría el motivo dentro de `detail`; el cliente lee
`reason` al mismo nivel que en `unsafe_topic` o `grader_unavailable` (ADR-036, ADR-053).
"""
from __future__ import annotations


class ReasonedError(Exception):
    def __init__(self, status_code: int, detail: str, reason: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.reason = reason
