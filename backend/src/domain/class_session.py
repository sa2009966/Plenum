"""Lo que el tutor sabe de la clase cuando el alumno pregunta en ella (ADR-054).

Solo lleva lo que el alumno ya está viendo. A propósito NO tiene campos para la
letra correcta, las ideas clave de una abierta ni la respuesta modelo de la
comprobación pendiente: lo que no entra en el prompt no se puede filtrar, por
mucho que el alumno insista.
"""
from __future__ import annotations

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

    def __post_init__(self) -> None:
        object.__setattr__(self, "lesson_excerpt", (self.lesson_excerpt or "")[:MAX_LESSON_EXCERPT])
        object.__setattr__(self, "pending_check", tuple(self.pending_check)[:MAX_PENDING_CHECK])
