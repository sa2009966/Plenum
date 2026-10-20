"""Etiquetado heurístico de conceptos en ítems de quiz (sin LLM)."""
from __future__ import annotations

import re
from dataclasses import replace

from src.domain.concept_identity import canonicalize_concept
from src.domain.subject_areas import EXACTAS, SOCIALES, area_of_subject, matches_area
from src.domain.value_objects.question import QuizQuestion

#: (patrón, concepto, área). El área evita que `desigualdad` de un quiz de
#: álgebra acabe etiquetada como `desigualdad social` (ADR-011).
_DEFAULT_PATTERNS: list[tuple[re.Pattern[str], str, str | None]] = [
    (re.compile(r"\bvariables?\b", re.I), "variable", EXACTAS),
    (re.compile(r"\bconstantes?\b", re.I), "constante", EXACTAS),
    (re.compile(r"\becuaci[oó]n(es)?\b|\bdespejar\b|\bresolver\b", re.I), "ecuacion", EXACTAS),
    (re.compile(r"\bdistributiv", re.I), "propiedad distributiva", EXACTAS),
    (re.compile(r"\bexpresi[oó]n(es)?\b", re.I), "expresion algebraica", EXACTAS),
    (re.compile(r"\bsuma\b|\brest(a|ar)\b|\bmultiplic", re.I), "operaciones", EXACTAS),
    # Ciencias sociales / desigualdad LATAM
    (re.compile(r"\bdesigualdad(es)?\b", re.I), "desigualdad social", SOCIALES),
    (re.compile(r"\bpobreza\b|\bindigencia\b", re.I), "pobreza", SOCIALES),
    (re.compile(r"\bgini\b|\bcoeficiente\s+de\s+gini\b", re.I), "indice de gini", SOCIALES),
    (re.compile(r"\bmobilidad\s+social\b|\bmovilidad\s+social\b", re.I), "movilidad social", SOCIALES),
    (re.compile(r"\binformalidad\b|\bempleo\s+informal\b", re.I), "informalidad laboral", SOCIALES),
    (re.compile(r"\beducaci[oó]n\b|\bbrecha\s+educativ", re.I), "brecha educativa", SOCIALES),
    (re.compile(r"\bextractiv", re.I), "extractivismo", SOCIALES),
    (re.compile(r"\blatin\s*am[eé]ric", re.I), "latinoamerica", SOCIALES),
]


def _fold(text: str) -> str:
    return canonicalize_concept(text)


class ConceptTagger:
    """Asigna concept_tags a preguntas usando keywords y conceptos del documento."""

    def __init__(self, extra_patterns: list[tuple] | None = None) -> None:
        self._patterns = list(_DEFAULT_PATTERNS)
        if extra_patterns:
            # Los patrones extra pueden venir sin área: se tratan como neutros.
            self._patterns.extend(
                p if len(p) == 3 else (p[0], p[1], None) for p in extra_patterns
            )

    def tag_question(
        self,
        question: QuizQuestion,
        document_concepts: tuple[str, ...] = (),
        subject: str | None = None,
    ) -> QuizQuestion:
        if question.concept_tags:
            return question
        area = area_of_subject(subject)
        blob = _fold(question.text + " " + " ".join(question.options.values()))
        tags: list[str] = []
        for pattern, label, pattern_area in self._patterns:
            if not matches_area(pattern_area, area):
                continue
            if pattern.search(blob) and label not in tags:
                tags.append(canonicalize_concept(label))
        for concept in document_concepts:
            key = canonicalize_concept(concept)
            if not key:
                continue
            if key in blob and key not in tags:
                tags.append(key)
        if not tags and document_concepts:
            tags.append(canonicalize_concept(document_concepts[0]))
        if not tags:
            # Sin señal, la pregunta se queda SIN etiquetar. Antes se inventaba
            # un concepto llamado "general" que entraba al perfil como si fuera
            # real: engordaba `mastery_by_concept`, competía por el foco y podía
            # llegar al gate. No saber de qué es un ítem es un dato; fabricar un
            # concepto para taparlo, no (ADR-011).
            return question
        # `replace` conserva el tipo y la rúbrica de una pregunta abierta (ADR-053).
        return replace(question, concept_tags=tuple(tags[:5]))

    def tag_questions(
        self,
        questions: list[QuizQuestion],
        document_concepts: tuple[str, ...] = (),
        subject: str | None = None,
    ) -> list[QuizQuestion]:
        return [self.tag_question(q, document_concepts, subject) for q in questions]
