"""Qué se enseña y qué no: la decisión sobre un tema o un mensaje (ADR-036).

Plenum lo usan menores. En producción apareció una ruta "Hacer un arma" con temario y
clases generadas: nada filtraba lo que el estudiante pedía aprender. El moderador
(un puerto) mide; esta política decide, con umbrales inyectados (invariantes 2 y 6).

No se usa el `flagged` del proveedor tal cual: marcaba "Genocidio de Ruanda" (violencia
0.42) o "cómo funciona la bomba atómica" (ilícito 0.21), que son temas de clase. Aquí
la violencia descriptiva no bloquea; lo que bloquea es pedir **cómo hacer** daño
(ilícito), contenido sexual, odio y amenazas. La autolesión no se rechaza: se acompaña.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class SafetyAction(str, Enum):
    ALLOW = "allow"
    #: El tema o el mensaje no se trabaja; se redirige con amabilidad.
    REFUSE = "refuse"
    #: Señal de autolesión: no es un tema que rechazar, es una persona que acompañar.
    SUPPORT = "support"


@dataclass(frozen=True)
class SafetyThresholds:
    """Desde cuánto puntaje (0-1) una categoría decide. Calibrado con textos reales.

    Mediciones con omni-moderation (2026-10-03): "Hacer un arma" ilícito-violento 0.92,
    "receta para hacer pólvora" 0.96, "cómo envenenar a alguien" 0.86, "Fabricación de
    armas químicas" 0.61; en cambio "Química de los explosivos" 0.30 y "Drogas y sus
    efectos en el cerebro" 0.17 pasan. "esta tarea me mata" da autolesión 0.13.
    """

    illicit: float = 0.5
    sexual: float = 0.5
    #: Más estricto: cualquier indicio con menores basta.
    sexual_minors: float = 0.2
    hate: float = 0.5
    threatening: float = 0.5
    #: Violencia gráfica explícita; la violencia histórica o descriptiva no cuenta.
    graphic_violence: float = 0.7
    self_harm: float = 0.5


@dataclass(frozen=True)
class SafetyVerdict:
    action: SafetyAction
    #: La categoría que decidió (para métricas y registro), None si se permite.
    category: str | None = None

    @property
    def allowed(self) -> bool:
        return self.action is SafetyAction.ALLOW


ALLOW = SafetyVerdict(SafetyAction.ALLOW)

#: Categorías del moderador → umbral que las gobierna. Las de autolesión van aparte.
_REFUSE_BY = (
    ("illicit", "illicit"),
    ("illicit/violent", "illicit"),
    ("sexual", "sexual"),
    ("sexual/minors", "sexual_minors"),
    ("hate", "hate"),
    ("hate/threatening", "threatening"),
    ("harassment/threatening", "threatening"),
    ("violence/graphic", "graphic_violence"),
)
_SELF_HARM = ("self-harm", "self-harm/intent", "self-harm/instructions")


class ContentSafetyPolicy:
    def __init__(self, thresholds: SafetyThresholds | None = None) -> None:
        self._t = thresholds or SafetyThresholds()

    def decide(self, scores: Mapping[str, float]) -> SafetyVerdict:
        # Autolesión primero: si alguien lo está pasando mal, eso manda sobre el resto.
        for categoria in _SELF_HARM:
            if scores.get(categoria, 0.0) >= self._t.self_harm:
                return SafetyVerdict(SafetyAction.SUPPORT, categoria)
        for categoria, umbral in _REFUSE_BY:
            if scores.get(categoria, 0.0) >= getattr(self._t, umbral):
                return SafetyVerdict(SafetyAction.REFUSE, categoria)
        return ALLOW


class UnsafeTopicError(ValueError):
    """El tema no se puede trabajar. Hereda de ValueError: los routers ya lo
    convierten en 422 con el mensaje, que el cliente muestra al estudiante."""

    def __init__(self, verdict: SafetyVerdict) -> None:
        self.verdict = verdict
        super().__init__(safety_message(verdict))


#: Lo lee el estudiante. Sin sermón ni detalle de por qué: una salida y una invitación.
REFUSE_MESSAGE = (
    "Ese tema no lo puedo trabajar contigo, porque podría servir para hacer daño. "
    "Si te interesa algo cercano desde el lado de la ciencia, la historia o la "
    "seguridad, dime y lo vemos juntos. ¿Qué otro tema quieres aprender?"
)

#: Autolesión: cercanía, un adulto de confianza y ayuda inmediata. Se escribe también
#: para la hipérbole ("me quiero morir xd" por una tarea): no asusta y deja seguir.
SUPPORT_MESSAGE = (
    "Lo que escribiste me importa. Si lo dijiste por la frustración con el tema, "
    "te entiendo, y podemos ir más despacio, paso a paso. Pero si de verdad estás "
    "pensando en hacerte daño o no quieres seguir viviendo, no te quedes con eso a "
    "solas: cuéntaselo ahora a un adulto de confianza (tu familia, un profesor o un "
    "orientador). Si estás en peligro, llama a los servicios de emergencia de tu país "
    "(911 o 112) o a una línea de ayuda emocional. Aquí sigo cuando quieras."
)


def safety_message(verdict: SafetyVerdict) -> str:
    return SUPPORT_MESSAGE if verdict.action is SafetyAction.SUPPORT else REFUSE_MESSAGE
