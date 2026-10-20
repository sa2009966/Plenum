"""Cuántas abiertas, dónde y cómo viajan (ADR-053)."""
from uuid import uuid4

import pytest

from src.domain.aggregates.quiz_aggregate import QuizAggregate
from src.domain.aggregates.quiz_attempt_aggregate import QuizAttemptAggregate
from src.domain.assessment import AssessmentMix, check_layout, interleave, split_by_weight
from src.domain.events.domain_events import AssessmentChosenEvent
from src.domain.open_answers import OpenAnswerGrade, OpenVerdict
from src.domain.services.diagnostic_planner import (
    PlacementRound,
    fit_to_plan,
    plan_diagnostic,
    resized,
    with_open_items,
)
from src.domain.value_objects.question import Difficulty, QuizQuestion
from src.infrastructure.ia.base_chat_analyst import BaseChatAnalyst
from src.infrastructure.mongodb.outbox_event_bus import _deserialize, _serialize
from src.infrastructure.mongodb.quiz_attempt_repository import MongoDBQuizAttemptRepository
from src.infrastructure.mongodb.quiz_repository import MongoDBQuizRepository

ABIERTA = QuizQuestion(text="Explica X", options={}, correct_answer="", kind="open",
                       key_points=("idea uno", "idea dos"), model_answer="Ejemplo.", concept_tags=("x",))
CERRADA = QuizQuestion(text="¿X?", options={"A": "a", "B": "b"}, correct_answer="A", concept_tags=("x",))


def test_las_abiertas_se_reparten_a_lo_largo():
    assert interleave(3, 6) == ("choice", "open", "choice", "open", "choice", "open")
    assert interleave(0, 3) == ("choice",) * 3
    assert interleave(4, 4) == ("open",) * 4
    assert split_by_weight(4, [4, 2]) == [3, 1]


@pytest.mark.parametrize("o, c", [(0, 0), (11, 0), (-1, 2), (8, 8), (True, 2)])
def test_una_mezcla_invalida_no_existe(o, c):
    with pytest.raises(ValueError):
        AssessmentMix(o, c)


def test_la_comprobacion_se_estira_ordenada_de_facil_a_dificil():
    dif, tipos = check_layout((Difficulty.MEDIUM, Difficulty.EASY), AssessmentMix(2, 3))
    assert [d.value for d in dif] == ["easy", "easy", "medium", "medium", "medium"]
    assert tipos.count("open") == 2 and len(tipos) == 5


def test_la_nivelacion_abierta_tiene_4_y_respeta_el_reparto():
    for ronda in PlacementRound:
        plan = with_open_items(resized(plan_diagnostic("ecuaciones", None, ronda), 4), 4)
        assert plan.total_items == 4 and plan.open_items == 4
        assert all(r.items > 0 for r in plan.rungs)


def test_fit_to_plan_no_deja_que_una_cerrada_ocupe_el_hueco_de_una_abierta():
    plan = with_open_items(resized(plan_diagnostic("ecuaciones", None, PlacementRound.BASE), 2), 1)
    d = plan.rungs[0].difficulty
    cerradas = [QuizQuestion(text=f"¿{i}?", options={"A": "a", "B": "b"}, correct_answer="A", difficulty=d) for i in range(3)]
    elegidas, cumple = fit_to_plan(cerradas, plan)
    assert not cumple and all(not q.is_open for q in elegidas)


def test_el_agregado_combina_abiertas_corregidas_con_cerradas():
    quiz = QuizAggregate.create(None, uuid4(), [ABIERTA, CERRADA], topic="x")
    with pytest.raises(ValueError):
        quiz.grade({0: "mi respuesta", 1: "A"})  # falta la corrección de la abierta
    parcial = OpenAnswerGrade(OpenVerdict.PARTIAL, 0.5, (True, False), "Falta una idea.")
    nota = quiz.grade({0: "mi respuesta", 1: "A"}, {0: parcial})
    assert nota.per_question_score == (0.5, 1.0) and nota.score == 15
    assert nota.per_question_correct == (False, True)


def test_un_intento_viejo_sin_creditos_vale_lo_que_acerto():
    viejo = QuizAttemptAggregate(per_question_correct=[True, False])
    assert (viejo.score_at(0), viejo.score_at(1)) == (1.0, 0.0)


def test_una_abierta_valida_su_forma():
    with pytest.raises(ValueError):
        QuizQuestion(text="X", options={"A": "a"}, correct_answer="", kind="open", key_points=("i",))
    with pytest.raises(ValueError):
        QuizQuestion(text="X", options={}, correct_answer="", kind="open", key_points=())
    with pytest.raises(ValueError):
        QuizQuestion(text="X", options={}, correct_answer="", kind="rara")


def test_el_parser_lee_abiertas_y_rechaza_una_abierta_con_opciones():
    quiz = BaseChatAnalyst._quiz_desde_json(None, {"questions": [
        {"kind": "open", "text": "Explica X", "key_points": ["a  b", "c"], "model_answer": "m", "difficulty": "easy",
         "concept_tags": ["x"]},
        {"text": "¿Y?", "options": {"A": "1", "B": "2"}, "correct_answer": "B"},
    ]})
    assert quiz.questions[0].is_open and quiz.questions[0].key_points == ("a b", "c")
    assert not quiz.questions[1].is_open
    from src.domain.ports.ia_analyst import IAAnalysisError

    with pytest.raises(IAAnalysisError):
        BaseChatAnalyst._quiz_desde_json(None, {"questions": [
            {"kind": "open", "text": "X", "options": {"A": "1"}, "key_points": ["a"]}]})


def test_la_preferencia_viaja_por_el_outbox():
    e = AssessmentChosenEvent(aggregate_id=uuid4(), student_id=uuid4(), open_questions=2, choice_questions=4)
    vuelta = _deserialize(_serialize(e))
    assert (vuelta.open_questions, vuelta.choice_questions, vuelta.event_id) == (2, 4, e.event_id)


def test_mongo_guarda_y_lee_abiertas_y_creditos():
    quiz = QuizAggregate.create(None, uuid4(), [ABIERTA, CERRADA], topic="x")
    leido = MongoDBQuizRepository._from_doc(MongoDBQuizRepository._to_doc(quiz))
    assert leido.questions[0] == quiz.questions[0] and not leido.questions[1].is_open

    nota = quiz.grade({0: "r", 1: "B"}, {0: OpenAnswerGrade(OpenVerdict.CORRECT, 1.0, (True, True), "Bien.")})
    intento = QuizAttemptAggregate.create(quiz.id, None, uuid4(), {0: "r", 1: "B"}, nota)
    otra = MongoDBQuizAttemptRepository._from_doc(MongoDBQuizAttemptRepository._to_doc(intento))
    assert otra.per_question_score == [1.0, 0.0]
    assert otra.open_results[0]["verdict"] == "correct" and otra.open_results[0]["feedback"] == "Bien."


def test_opciones_numericas_del_modelo_se_vuelven_texto():
    """Capturado con el modelo real: {"A": 4, ...} daba 500 al responder la nivelación."""
    quiz = BaseChatAnalyst._quiz_desde_json(None, {"questions": [
        {"text": "¿x en 2x = 8?", "options": {"a": 4, "b": 3, "c": 1, "d": 2}, "correct_answer": "a"}]})
    q = quiz.questions[0]
    assert q.options == {"A": "4", "B": "3", "C": "1", "D": "2"} and q.correct_answer == "A"
