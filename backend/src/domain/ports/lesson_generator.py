"""Puerto del contenido de la clase (ADR-028). El modelo REDACTA; no decide.

Qué concepto, qué tipo de explicación y qué dificultad tienen las preguntas lo
fija `TeachingPolicy` y viaja en `LessonRequest`. El adaptador solo devuelve
texto y preguntas, y el backend valida su forma antes de usarlas.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.domain.aggregates.learning_path import LessonVariant
from src.domain.services.cognitive_style import CognitiveStyle
from src.domain.value_objects.question import Difficulty, QuizQuestion


@dataclass(frozen=True)
class LessonRequest:
    topic_label: str
    concept: str
    concept_title: str
    variant: LessonVariant
    #: Dificultad de cada pregunta de la comprobación (la decide el backend).
    check_difficulties: tuple[Difficulty, ...]
    level: str | None = None
    style: CognitiveStyle | None = None
    #: Concepto al que se volverá tras la remediación (para prometerlo).
    return_to_title: str | None = None
    #: Ejemplo anterior, para no repetirlo.
    avoid_example: str = ""
    #: Género con el que LARIA habla de sí misma (el de su voz, ADR-030).
    persona: str | None = None
    #: Minutos por sesión que eligió (ADR-033): dimensiona la explicación.
    session_minutes: int | None = None
    #: Ideas clave del módulo sacadas de fuentes reales (ADR-039): la explicación se
    #: apoya en ellas en vez de solo en lo que el modelo recuerde.
    key_points: tuple[str, ...] = ()
    #: Tipo de cada pregunta de la comprobación, en el mismo orden ("choice"/"open",
    #: ADR-053). Vacío = todas de opción múltiple, como antes.
    check_kinds: tuple[str, ...] = ()


@dataclass(frozen=True)
class Lesson:
    explanation: str
    example: str
    example_summary: str
    check: tuple[QuizQuestion, ...]

    @property
    def markdown(self) -> str:
        return f"{self.explanation.strip()}\n\n**Ejemplo.** {self.example.strip()}"


@dataclass(frozen=True)
class Source:
    """Una fuente que la búsqueda web devolvió de verdad (ADR-039). Nunca la escribe el modelo."""

    title: str
    url: str


@dataclass(frozen=True)
class SyllabusItem:
    title: str
    prerequisites: tuple[str, ...] = ()
    #: Ideas clave del subtema según las fuentes (ADR-039). Vacío si el temario no se investigó.
    key_points: tuple[str, ...] = ()
    sources: tuple[Source, ...] = ()


class LessonGenerator(ABC):
    @abstractmethod
    async def generate_lesson(self, request: LessonRequest) -> Lesson: ...

    async def propose_next_topics(self, topic_label: str, level: str | None) -> list[str]:
        """Temas para seguir tras completar uno que el grafo no cubre. No abstracto:
        sin él, solo se sugiere subir de nivel."""
        return []

    @abstractmethod
    async def propose_syllabus(
        self, topic_label: str, level: str | None, avoid: tuple[str, ...] = ()
    ) -> list[SyllabusItem]:
        """Temario de un tema (o de un tramo nuevo de su ruta, ADR-037). Se valida y se congela.

        `avoid`: subtemas que la ruta ya tiene; el tramo nuevo no los repite.
        """
