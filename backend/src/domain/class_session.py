"""Lo que el tutor sabe de la clase cuando el alumno pregunta en ella (ADR-054).

Solo lleva lo que el alumno ya está viendo. A propósito NO tiene campos para la
letra correcta, las ideas clave de una abierta ni la respuesta modelo de la
comprobación pendiente: lo que no entra en el prompt no se puede filtrar, por
mucho que el alumno insista.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

#: Lo que cabe de la explicación sin que la duda se ahogue en contexto.
MAX_LESSON_EXCERPT = 2_500
MAX_PENDING_CHECK = 12


@dataclass(frozen=True)
class ClassSession:
    topic_label: str
    concept_title: str
    #: La clave canónica del concepto del paso: a ella va la señal de una duda.
    concept: str = ""
    #: Extracto de la explicación que el alumno tiene delante.
    lesson_excerpt: str = ""
    #: Ideas clave del módulo sacadas de fuentes (ADR-039), no de la comprobación.
    key_points: tuple[str, ...] = ()
    #: Solo los ENUNCIADOS de la comprobación pendiente, sin opciones ni respuestas.
    pending_check: tuple[str, ...] = ()
    #: La pregunta de este turno es de otro tema (`fuera_de_tema`): respuesta corta y
    #: de vuelta a la clase.
    off_topic: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "lesson_excerpt", (self.lesson_excerpt or "")[:MAX_LESSON_EXCERPT])
        object.__setattr__(self, "pending_check", tuple(self.pending_check)[:MAX_PENDING_CHECK])


#: Palabras que no dicen de qué trata una pregunta: gramaticales y de pedir ayuda.
_VACIAS = frozenset(
    """
    algo alguien alguna alguno algunos antes aqui asi cada como con contra cual cuales cuando
    cuanto cuanta cuantos cuantas de del desde donde dos ella ellas ello ellos entre era eres
    esa esas ese eso esos esta estas este esto estos estoy estas fue hay hace hacer haces hacia
    hasta las los mas mismo mucho muy nada nunca otra otro otros para pero poco porque puede
    puedes pues que quien quienes sea segun sera ser sido sin sobre solo son soy sus tambien
    tanto tiene tienes todo todos tras una uno unos unas vez veces cosa cosas parte forma manera
    dime decir explica explicas explicame explicarme cuentame cuenta contar quiero quieres
    podrias puedo saber sabes entiendo entender entiende entendi ayuda ayudame ayudar
    ejemplo ejemplos pregunta preguntas respuesta respuestas clase paso tema favor gracias
    bien mejor ahora luego otra vale bueno vamos seguir sigue sigues primero entonces
    """.split()
)
#: Con menos palabras con contenido no se puede saber de qué trata: se da por de la clase.
_MIN_PALABRAS_DESVIO = 3


def _palabras(texto: str) -> set[str]:
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", (texto or "").lower()) if unicodedata.category(c) != "Mn"
    )
    return {p for p in re.findall(r"[a-z]+", sin_tildes) if len(p) >= 4 and p not in _VACIAS}


def _parecidas(a: str, b: str) -> bool:
    """La misma palabra con otra terminación (lado/lados, ecuación/ecuaciones)."""
    return a.startswith(b) or b.startswith(a) or (len(a) >= 6 and a[:6] == b[:6])


def fuera_de_tema(pregunta: str, sesion: ClassSession) -> bool:
    """Si una pregunta hecha en clase es claramente de otro tema.

    Conservador a propósito: tomar una duda real por desvío y contestarla en dos
    frases es peor que dejar pasar un desvío. Solo lo es si la pregunta tiene al
    menos tres palabras con contenido, ninguna se parece a nada de la clase (tema,
    paso, explicación, ideas clave, comprobación) y no muestra confusión ni pide
    ayuda, que siempre se toman como dudas de la clase.
    """
    from src.domain.services.learning_signal_detector import LearningSignalDetector, LearningSignalKind

    palabras = _palabras(pregunta)
    if len(palabras) < _MIN_PALABRAS_DESVIO:
        return False
    if LearningSignalDetector().detect(pregunta).kind != LearningSignalKind.NONE:
        return False
    clase = _palabras(
        " ".join(
            (sesion.topic_label, sesion.concept_title, sesion.concept, sesion.lesson_excerpt,
             *sesion.key_points, *sesion.pending_check)
        )
    )
    return not any(_parecidas(p, c) for p in palabras for c in clase)
