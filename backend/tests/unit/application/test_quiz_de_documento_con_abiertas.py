"""Los quizzes de documentos y del chat también llevan preguntas abiertas (ADR-053).

Pendiente: solo generaban opción múltiple, aunque la nivelación, la práctica, la
prueba de paso y la clase ya mezclaban abiertas. Con OPEN_QUESTIONS_ENABLED, ahora
siguen la misma mezcla (la del body, si no la elegida, si no 3 + 3); apagado, nada
cambia.
"""
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.application.services.quiz_service import QuizService
from src.domain.aggregates.document_aggregate import DocumentAggregate
from src.domain.assessment import AssessmentMix, fit_to_mix
from src.domain.ports.ia_analyst import IAAnalyst
from src.domain.ports.repositories import DocumentRepository
from src.domain.services.tutor_policy import TutorPolicy
from src.domain.value_objects.question import Quiz, QuizQuestion
from src.infrastructure.persistence.in_memory_quiz_attempt_repo import InMemoryQuizAttemptRepository
from src.infrastructure.persistence.in_memory_quiz_repo import InMemoryQuizRepository
from src.infrastructure.persistence.in_memory_tutor_interaction_repo import (
    InMemoryTutorInteractionRepository,
)


def _cerrada(i):
    return QuizQuestion(text=f"C{i}", options={"A": "sí", "B": "no"}, correct_answer="A", concept_tags=("historia",))


def _abierta(i):
    return QuizQuestion(
        text=f"A{i}: explica por qué", options={}, correct_answer="", kind="open",
        key_points=("idea uno", "idea dos"), model_answer="Porque sí.", concept_tags=("historia",),
    )


def _quiz(abiertas, cerradas):
    return Quiz(questions=[_abierta(i) for i in range(abiertas)] + [_cerrada(i) for i in range(cerradas)])


def _servicio(ia, abiertas_activas=True):
    doc_repo = AsyncMock(spec=DocumentRepository)
    owner = uuid4()
    doc = DocumentAggregate.upload(owner, "t.txt", "contenido", "Historia")
    doc_repo.find_by_id.return_value = doc
    servicio = QuizService(
        document_repository=doc_repo, quiz_repository=InMemoryQuizRepository(),
        attempt_repository=InMemoryQuizAttemptRepository(),
        interaction_repository=InMemoryTutorInteractionRepository(),
        ia_analyst=ia, event_bus=None, open_questions_enabled=abiertas_activas,
    )
    return servicio, doc, owner


def _tipos(public):
    return sorted(q.kind for q in public.questions)


@pytest.mark.asyncio
async def test_con_abiertas_el_quiz_del_documento_sigue_la_mezcla_por_defecto():
    ia = AsyncMock(spec=IAAnalyst)
    ia.generate_quiz.return_value = _quiz(3, 3)
    servicio, doc, owner = _servicio(ia)

    public = await servicio.generate(doc.id, owner, num_questions=5)

    assert _tipos(public) == ["choice"] * 3 + ["open"] * 3
    args, kwargs = ia.generate_quiz.await_args
    assert args[1] == 6 and kwargs["open_items"] == 3


@pytest.mark.asyncio
async def test_la_mezcla_del_body_manda():
    ia = AsyncMock(spec=IAAnalyst)
    ia.generate_quiz.return_value = _quiz(1, 3)
    servicio, doc, owner = _servicio(ia)

    public = await servicio.generate(doc.id, owner, assessment=AssessmentMix(1, 3))

    assert _tipos(public) == ["choice"] * 3 + ["open"]
    assert ia.generate_quiz.await_args.kwargs["open_items"] == 1


@pytest.mark.asyncio
async def test_si_el_modelo_se_queda_corto_de_abiertas_se_regenera_una_vez():
    ia = AsyncMock(spec=IAAnalyst)
    ia.generate_quiz.side_effect = [_quiz(0, 6), _quiz(3, 4)]
    servicio, doc, owner = _servicio(ia)

    public = await servicio.generate(doc.id, owner)

    assert ia.generate_quiz.await_count == 2
    assert _tipos(public) == ["choice"] * 3 + ["open"] * 3, "lo que sobra se descarta"


@pytest.mark.asyncio
async def test_apagadas_el_quiz_es_como_antes():
    ia = AsyncMock(spec=IAAnalyst)
    ia.generate_quiz.return_value = _quiz(0, 2)
    servicio, doc, owner = _servicio(ia, abiertas_activas=False)

    public = await servicio.generate(doc.id, owner, num_questions=2)

    assert _tipos(public) == ["choice", "choice"]
    args, kwargs = ia.generate_quiz.await_args
    assert args[1] == 2 and kwargs.get("open_items", 0) == 0


def test_ajustar_a_la_mezcla_toma_cada_tipo_en_orden_y_dice_si_cumple():
    preguntas = [_cerrada(0), _abierta(0), _cerrada(1), _abierta(1), _cerrada(2)]

    ajustadas, cumple = fit_to_mix(preguntas, AssessmentMix(1, 2))
    assert [q.text for q in ajustadas] == ["C0", "A0: explica por qué", "C1"] and cumple

    _, cumple = fit_to_mix([_cerrada(0)], AssessmentMix(1, 1))
    assert cumple is False


def test_el_prompt_del_quiz_pide_las_abiertas_con_su_rubrica():
    con = TutorPolicy().generate_quiz("texto", 6, None, open_items=2).system
    sin = TutorPolicy().generate_quiz("texto", 6, None).system

    assert "2 abiertas y 4 de opción múltiple" in con and '"kind": "open"' in con
    assert "abierta" not in sin.lower() and "opción múltiple" in sin
