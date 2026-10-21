"""Lo que el tutor sabe del estudiante cuando no hay material (ADR-022).

Con material decide el motor pedagógico, con mastery por concepto. Sin material
no hay conceptos medidos del documento, pero sí dos datos que el estudiante dio
él mismo: su nivel en los temas en que se niveló y cómo quiere que le expliquen.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from src.domain.services.cognitive_style import CognitiveStyle

#: Cuántos niveles guardados se mencionan cuando no hay un tema concreto.
MAX_LEVELS_IN_PROMPT = 5


from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from src.domain.class_session import ClassSession

@dataclass(frozen=True)
class LearnerContext:
    style: CognitiveStyle | None = None
    #: `(etiqueta, nivel)` del tema que pidió aprender, si ya se niveló en él.
    topic_level: tuple[str, str] | None = None
    #: Otros niveles guardados `(etiqueta, nivel)`, solo si no hay `topic_level`.
    levels: tuple[tuple[str, str], ...] = ()
    #: Pidió que se le pregunte cómo le gusta aprender (ADR-023).
    ask_style: bool = False
    #: Acaba de decir cómo prefiere aprender, y ya quedó guardado (ADR-023).
    style_just_chosen: bool = False
    #: Género con el que LARIA habla de sí misma: el de la voz elegida (ADR-030).
    persona: str | None = None
    #: Respuesta que salió casi igual a una anterior y se está regenerando (ADR-040).
    avoid_reply: str = ""
    #: La clase en la que pregunta, si pregunta desde una (ADR-054).
    class_session: "ClassSession | None" = None

    def __bool__(self) -> bool:
        return bool(
            self.style or self.topic_level or self.levels or self.ask_style or self.style_just_chosen
            or self.persona or self.avoid_reply or self.class_session
        )


#: Las opciones que el tutor ofrece en el chat. Son las mismas de la tarjeta del
#: cliente, en el mismo orden, para que "la 4" signifique lo mismo en los dos.
STYLE_OPTIONS: tuple[tuple[str, str | None], ...] = (
    ("Sencillo, sin tecnicismos", "simple"),
    ("Paso a paso", "step_by_step"),
    ("Con ejemplos y analogías", "analogy"),
    ("Con esquemas y dibujos", "visual"),
    ("Con fórmulas y demostraciones", "mathematical"),
    ("Técnico y riguroso", "technical"),
    ("Que lo decida LARIA", None),
)

_NUMERO = re.compile(r"^\W*(?:la\s+|el\s+|opci[oó]n\s+|n[uú]mero\s+)?([1-7])\b", re.I)
_QUE_DECIDA = re.compile(r"\bdecid(?:a|as|e|es|ir)\b|\bque\s+elijas\b|\bme\s+da\s+igual\b", re.I)


def tutor_offered_styles(texto: str) -> bool:
    """Si el último mensaje del tutor ofreció las opciones de estilo."""
    t = (texto or "").lower()
    return "con esquemas y dibujos" in t and "que lo decida laria" in t


def style_from_option_reply(texto: str) -> tuple[bool, str | None]:
    """Respuesta a las opciones: `(respondió, estilo)`. Estilo None = que decida LARIA.

    Solo tiene sentido justo después de que el tutor las ofreciera: fuera de ahí,
    "la 4" o "con dibujos" significan otra cosa.
    """
    m = _NUMERO.search(texto or "")
    if m:
        return True, STYLE_OPTIONS[int(m.group(1)) - 1][1]
    if _QUE_DECIDA.search(texto or ""):
        return True, None
    t = (texto or "").lower()
    for etiqueta, valor in STYLE_OPTIONS[:-1]:
        clave = etiqueta.lower().split(", ")[0].replace("con ", "").split(" y ")[0]
        if clave in t:
            return True, valor
    return False, None
