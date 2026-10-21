"""Qué cambia en un paso de la clase según el método de estudio (ADR-055, fase 4).

Lo decide el dominio; el modelo solo redacta lo que se le pide. Puro: la ruta y el
dominio por concepto entran como argumentos. La comprobación del paso se mantiene
en todos los métodos: es la evidencia calificada (una duda no es una nota).
"""
from __future__ import annotations

from dataclasses import dataclass

BEFORE = "before"
AFTER = "after"
#: Pasos del ejemplo resuelto: con menos no hay nada que completar; con más, no cabe en el móvil.
MIN_WORKED_STEPS = 2
MAX_WORKED_STEPS = 8


@dataclass(frozen=True)
class MethodPlan:
    method: str | None = None
    #: Concepto ya superado sobre el que va una pregunta de repaso (recuerdo activo, intercalado).
    review_concept: str | None = None
    review_position: str = AFTER
    #: «Explícalo tú»: la última pregunta de la comprobación es abierta y pide explicarlo.
    explain_it: bool = False
    #: «Preguntarse el porqué»: la explicación avanza con preguntas «¿por qué…?».
    why_guided: bool = False
    #: Ejemplos resueltos: cuántos pasos se ocultan (None = sin ejemplo por pasos).
    worked_hidden: int | None = None
    #: Si el método pedido no se aplicó tal cual, por qué (para `teaching.reason`).
    note: str = ""


def plan_for(
    method: str | None,
    *,
    current: str | None,
    passed: list[str],
    tier: str | None,
    understood_streak: int,
    effective_mastery: dict[str, float] | None = None,
) -> MethodPlan:
    """El plan del paso para el método efectivo (ya validado por `effective_method`)."""
    anteriores = [c for c in passed if c and c != current]
    if method == "active_recall":
        # Recuperar lo último que superó: es práctica de recuperación y además espacia.
        return MethodPlan(method, review_concept=anteriores[-1] if anteriores else None, review_position=BEFORE)
    if method == "interleaving":
        if len(anteriores) < 2:
            return MethodPlan(
                "active_recall",
                review_concept=anteriores[-1] if anteriores else None,
                review_position=BEFORE,
                note="Aún no hay dos conceptos superados para intercalar: esta vez, recuerdo activo.",
            )
        dominio = effective_mastery or {}
        # El más olvidado según el modelo de memoria; sin medición, el más antiguo.
        elegido = min(anteriores, key=lambda c: (dominio.get(c, 2.0), anteriores.index(c)))
        return MethodPlan(method, review_concept=elegido, review_position=AFTER)
    if method == "feynman":
        return MethodPlan(method, explain_it=True)
    if method == "elaboration":
        return MethodPlan(method, why_guided=True)
    if method == "worked_examples":
        if tier == "avanzado":
            return MethodPlan(note="En el nivel avanzado los ejemplos resueltos estorban más que ayudan: esta clase sigue como siempre.")
        # Desvanecimiento fijo: completo la primera vez; un paso menos por cada acierto.
        return MethodPlan(method, worked_hidden=max(0, understood_streak))
    return MethodPlan()


def fade(steps: list[str], hidden: int) -> list[tuple[str, bool]]:
    """Oculta los últimos `hidden` pasos (desvanecimiento hacia atrás); el primero siempre se ve."""
    limpios = [s for s in (str(x).strip() for x in steps) if s][:MAX_WORKED_STEPS]
    ocultos = max(0, min(int(hidden), len(limpios) - 1))
    corte = len(limpios) - ocultos
    return [(texto, i >= corte) for i, texto in enumerate(limpios)]
