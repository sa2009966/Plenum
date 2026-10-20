"""Cuántas preguntas abiertas y de opción múltiple lleva una evaluación (ADR-053).

El estudiante lo configura antes de empezar (3 + 3 por defecto) y el servidor lo
valida: nada negativo, nada vacío, nada que convierta una comprobación en un examen.
Dónde va cada tipo lo decide el dominio, no el modelo: así se puede comprobar que lo
generado cumple.
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_OPEN = 3
DEFAULT_CHOICE = 3
MAX_PER_KIND = 10
MAX_TOTAL = 12
#: Preguntas por ronda de nivelación cuando son abiertas: escribir lleva más que
#: marcar, sobre todo en el móvil. Confirmado por el usuario el 20-oct-2026 (ADR-053).
PLACEMENT_OPEN_ITEMS = 4


@dataclass(frozen=True)
class AssessmentMix:
    open_questions: int = DEFAULT_OPEN
    choice_questions: int = DEFAULT_CHOICE

    def __post_init__(self) -> None:
        for nombre, n in (("open_questions", self.open_questions), ("choice_questions", self.choice_questions)):
            if not isinstance(n, int) or isinstance(n, bool) or not 0 <= n <= MAX_PER_KIND:
                raise ValueError(f"{nombre} debe ser un entero entre 0 y {MAX_PER_KIND}.")
        if not 1 <= self.total <= MAX_TOTAL:
            raise ValueError(f"Una evaluación lleva entre 1 y {MAX_TOTAL} preguntas.")

    @property
    def total(self) -> int:
        return self.open_questions + self.choice_questions

    def without_open(self) -> "AssessmentMix":
        """La misma cantidad, toda de opción múltiple (abiertas apagadas)."""
        return AssessmentMix(0, min(MAX_PER_KIND, self.total))


DEFAULT_MIX = AssessmentMix()


def interleave(n_open: int, total: int) -> tuple[str, ...]:
    """Qué posiciones son abiertas: repartidas a lo largo, no todas al final.

    Determinista: mismas cantidades, mismas posiciones. Con 3 de 6: c o c o c o.
    """
    n_open = max(0, min(n_open, total))
    if total <= 0:
        return ()
    abiertas = {int((k + 1) * total / n_open) - 1 for k in range(n_open)} if n_open else set()
    return tuple("open" if i in abiertas else "choice" for i in range(total))


def split_by_weight(total: int, weights: list[int]) -> list[int]:
    """Reparte `total` en proporción a `weights` (mayor resto). Pura."""
    suma = sum(weights)
    if total <= 0 or suma <= 0:
        return [0 for _ in weights]
    brutos = [total * w / suma for w in weights]
    enteros = [int(x) for x in brutos]
    sobran = total - sum(enteros)
    for i in sorted(range(len(brutos)), key=lambda i: brutos[i] - enteros[i], reverse=True)[:sobran]:
        enteros[i] += 1
    return enteros


def check_layout(base_difficulties: tuple, mix: AssessmentMix) -> tuple[tuple, tuple[str, ...]]:
    """Dificultad y tipo de cada pregunta de una comprobación de clase. Pura.

    La variante de la clase (ADR-028) da su patrón de dificultades; aquí se estira o
    se recorta a la cantidad elegida, ordenado de fácil a difícil, y se reparten
    las abiertas a lo largo.
    """
    orden = {"easy": 0, "medium": 1, "hard": 2}
    base = tuple(base_difficulties) or ()
    if not base:
        raise ValueError("La comprobación necesita al menos una dificultad de referencia.")
    estirado = [base[i % len(base)] for i in range(mix.total)]
    estirado.sort(key=lambda d: orden.get(getattr(d, "value", d), 1))
    return tuple(estirado), interleave(mix.open_questions, mix.total)
