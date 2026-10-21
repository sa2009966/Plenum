"""Validación y reequilibrio de cuestionarios generados por el LLM.

El modelo tiende a poner casi todas las correctas en 'A'. Eso infla mastery
y rompe la adaptación. LARIA corrige la distribución en dominio, sin otra
llamada al LLM.
"""
from __future__ import annotations

from dataclasses import replace
import random
import re
from collections import Counter

from src.domain.value_objects.question import QuizQuestion


#: Azar del sistema: no predecible a partir de preguntas anteriores.
_RNG = random.SystemRandom()


class QuizQualityError(ValueError):
    """El cuestionario no cumple criterios mínimos de evidencia fiable."""


def answer_key_distribution(questions: list[QuizQuestion]) -> dict[str, int]:
    return dict(Counter(q.correct_answer.upper() for q in questions))


def is_answer_key_skewed(questions: list[QuizQuestion], *, max_share: float = 0.6) -> bool:
    """True si una sola clave concentra más del max_share de respuestas correctas."""
    if len(questions) < 2:
        return False
    dist = answer_key_distribution(questions)
    dominant = max(dist.values())
    return (dominant / len(questions)) > max_share


def rebalance_answer_keys(questions: list[QuizQuestion]) -> list[QuizQuestion]:
    """Rota opciones de forma determinista para repartir claves correctas.

    No cambia el significado: solo reordena A/B/C/... y actualiza correct_answer.
    """
    if not questions:
        return []

    balanced: list[QuizQuestion] = []
    for index, question in enumerate(questions):
        keys = sorted(question.options.keys())
        n = len(keys)
        if n < 2:
            balanced.append(question)
            continue

        # Rotación acumulativa: pregunta i rota i posiciones.
        shift = index % n
        rotated_keys = keys[shift:] + keys[:shift]
        # Nuevo mapa: A->texto que antes estaba en rotated_keys[0], etc.
        # Queremos etiquetas canónicas A,B,C,... en orden.
        labels = [chr(ord("A") + i) for i in range(n)]
        # Posición de la respuesta correcta en el orden original
        old_correct_idx = keys.index(question.correct_answer)
        # Tras rotar la lista de valores según shift...
        values_in_old_order = [question.options[k] for k in keys]
        rotated_values = values_in_old_order[shift:] + values_in_old_order[:shift]
        new_options = {labels[i]: rotated_values[i] for i in range(n)}
        # La correcta se mueve: old_idx -> (old_idx - shift) mod n en el nuevo orden
        new_correct_idx = (old_correct_idx - shift) % n
        new_correct = labels[new_correct_idx]

        difficulty = question.difficulty
        balanced.append(
            # `replace`: conserva tipo, posición y concepto de repaso (ADR-053/055).
            replace(question, options=new_options, correct_answer=new_correct, difficulty=difficulty)
        )
    return balanced


#: Opciones que hablan de otras opciones: barajarlas les quita el sentido.
_REFERENCIA_A_OPCIONES = re.compile(
    r"\b(?:todas|ninguna|ambas)\s+(?:las\s+)?(?:anteriores|opciones)\b|\b[A-D]\s+y\s+[A-D]\b",
    re.IGNORECASE,
)


def shuffle_options(question: QuizQuestion, rng=None) -> QuizQuestion:
    """Baraja las opciones al azar y reasigna A, B, C… y la correcta.

    Los modelos ponen la correcta casi siempre en la misma letra (en las clases,
    la B): sin barajar, el estudiante aprende la letra, no el concepto, y la
    evidencia del perfil mide nada. `rng` es inyectable para los tests.
    """
    if len(question.options) < 2 or any(
        _REFERENCIA_A_OPCIONES.search(str(v)) for v in question.options.values()
    ):
        return question
    rng = rng or _RNG
    claves = sorted(question.options)
    textos = [question.options[k] for k in claves]
    correcta = textos[claves.index(question.correct_answer)]
    orden = list(range(len(textos)))
    rng.shuffle(orden)
    letras = [chr(ord("A") + i) for i in range(len(textos))]
    nuevas = {letras[i]: textos[j] for i, j in enumerate(orden)}
    nueva_correcta = next(letra for letra, texto in nuevas.items() if texto == correcta)
    # `replace`: barajar no puede borrar la posición ni el concepto de repaso (fase 4).
    return replace(question, options=nuevas, correct_answer=nueva_correcta)


def ensure_quiz_quality(questions: list[QuizQuestion], rng=None) -> list[QuizQuestion]:
    """Valida y baraja las opciones de TODAS las preguntas.

    Antes solo se reequilibraba con más del 60 % en una letra, y con una
    rotación predecible (la 1.ª pregunta no se movía, la 2.ª un lugar…).
    """
    if not questions:
        raise QuizQualityError("El cuestionario no tiene preguntas")
    for q in questions:
        if q.is_open:
            # Una abierta no tiene opciones que barajar; su rúbrica ya la validó
            # el value object (ADR-053).
            continue
        if len(q.options) < 2:
            raise QuizQualityError("Cada pregunta necesita al menos 2 opciones")
        if q.correct_answer not in q.options:
            raise QuizQualityError("correct_answer inválida")
    return [q if q.is_open else shuffle_options(q, rng) for q in questions]
