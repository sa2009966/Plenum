"""Métodos de estudio y ritmos: el catálogo y sus reglas (ADR-055).

Puro: los interruptores y el estado de la ruta entran como argumentos. Los textos
los escribe el backend, sin prometer lo que la evidencia no respalda.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StudyMethod:
    key: str
    name: str
    summary: str
    good_for: str


@dataclass(frozen=True)
class StudyPace:
    key: str
    name: str
    focus_minutes: int | None
    break_minutes: int | None


METHODS: tuple[StudyMethod, ...] = (
    StudyMethod(
        "active_recall", "Recuerdo activo",
        "Recordar sin mirar antes de volver a ver la explicación.",
        "Es lo que más ayuda a retener a largo plazo.",
    ),
    StudyMethod(
        "feynman", "Explícalo tú",
        "Explicar el tema con tus palabras, como si se lo enseñaras a alguien.",
        "Destapa lo que creías saber.",
    ),
    StudyMethod(
        "worked_examples", "Ejemplos resueltos",
        "Ver un ejemplo completo y luego completar tú los pasos que faltan.",
        "Ideal cuando el tema es nuevo.",
    ),
    StudyMethod(
        "elaboration", "Preguntarse el porqué",
        "La explicación avanza con preguntas «¿por qué…?» que conectan el tema con lo que ya sabes.",
        "Ayuda a entender, no solo a recordar.",
    ),
    StudyMethod(
        "interleaving", "Intercalado",
        "La práctica mezcla el tema nuevo con lo que ya superaste.",
        "Enseña a distinguir cuándo usar cada cosa.",
    ),
)
METHOD_KEYS = tuple(m.key for m in METHODS)

PACES: tuple[StudyPace, ...] = (
    StudyPace("free", "Libre", None, None),
    StudyPace("pomodoro_25_5", "Pomodoro 25/5", 25, 5),
    StudyPace("pomodoro_15_3", "Pomodoro 15/3", 15, 3),
)
PACE_KEYS = tuple(p.key for p in PACES)
DEFAULT_PACE = "free"

#: Conceptos superados en la ruta para poder intercalar: con menos no hay qué mezclar.
MIN_PASSED_FOR_INTERLEAVING = 2
#: Dominio medido por debajo del cual se recomiendan ejemplos resueltos.
LOW_MASTERY = 0.5

_NO_DISPONIBLE = {
    "open_questions_disabled": "Necesita las preguntas escritas, que aún no están activas.",
    "needs_two_passed_concepts": "Se abre cuando superes dos conceptos de esta ruta.",
}


@dataclass(frozen=True)
class Availability:
    available: bool
    reason: str | None = None

    @property
    def text(self) -> str | None:
        return _NO_DISPONIBLE.get(self.reason) if self.reason else None


def availability(key: str, *, open_questions: bool, passed_concepts: int | None) -> Availability:
    """Si el método se puede usar. `passed_concepts` None = sin ruta: solo cuentan los interruptores."""
    if key == "feynman" and not open_questions:
        return Availability(False, "open_questions_disabled")
    if key == "interleaving" and passed_concepts is not None and passed_concepts < MIN_PASSED_FOR_INTERLEAVING:
        return Availability(False, "needs_two_passed_concepts")
    return Availability(True)


def recommended(tier: str | None, concept_mastery: float | None) -> tuple[str, str] | None:
    """Como mucho un método recomendado, por el NIVEL (no por un «estilo»).

    Ejemplos resueltos para quien empieza (tramo básico) o tiene el concepto actual
    medido por debajo de 0,5. Nunca en avanzado: ahí estorban (inversión por pericia).
    `concept_mastery` None = sin evidencia, y sin evidencia no se recomienda nada
    por dominio (invariante 3).
    """
    if tier == "avanzado":
        return None
    if tier == "basico":
        return ("worked_examples", "Recomendado mientras el tema es nuevo para ti.")
    if concept_mastery is not None and concept_mastery < LOW_MASTERY:
        return ("worked_examples", "Recomendado: este concepto todavía te está costando.")
    return None


def effective_method(chosen: str | None, *, open_questions: bool, passed_concepts: int) -> tuple[str | None, str]:
    """El método que se aplica al paso y, si difiere del elegido, por qué (para `teaching.reason`)."""
    if chosen is None:
        return None, ""
    disp = availability(chosen, open_questions=open_questions, passed_concepts=passed_concepts)
    if disp.available:
        return chosen, ""
    nombre = next(m.name for m in METHODS if m.key == chosen)
    return None, f"«{nombre}» no está disponible ahora ({disp.text.rstrip('.').lower()}): esta clase sigue como siempre."
