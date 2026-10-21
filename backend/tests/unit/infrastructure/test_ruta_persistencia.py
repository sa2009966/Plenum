"""El estado de la clase sobrevive a Mongo: la siguiente petición continúa donde quedó (ADR-028)."""
from uuid import uuid4

from src.domain.aggregates.learning_path import (
    CheckOutcome,
    LearningPathAggregate,
    LessonVariant,
    ModuleKind,
    TeachingPhase,
)
from src.infrastructure.mongodb.learning_path_repository import MongoDBLearningPathRepository as Repo


def test_el_estado_de_la_clase_hace_ida_y_vuelta_completo():
    p = LearningPathAggregate.create_for_topic(
        uuid4(), "fraccion", "Fracciones",
        [{"concept": "operaciones", "kind": "prerequisite"},
         {"concept": "fraccion", "prerequisites": ["operaciones"], "kind": "content"}],
    )
    p.start_teaching("operaciones", LessonVariant.REMEDIATE, phase=TeachingPhase.REMEDIATION,
                     return_to="fraccion", reason="falta la base")
    quiz = uuid4()
    p.deliver_lesson("## Explicación", "ejemplo de pizza", quiz)
    p.record_check(CheckOutcome.NOT_UNDERSTOOD)
    p.start_teaching("operaciones", LessonVariant.REFORMULATE, return_to="fraccion", reason="otra manera")
    p.deliver_lesson("## Otra", "ejemplo de dinero", uuid4())
    p.mark_passed("numero entero")

    r = Repo._from_doc(Repo._to_doc(p))

    t, o = r.teaching, p.teaching
    assert (t.phase, t.concept, t.return_to, t.variant) == (TeachingPhase.CHECK, "operaciones", "fraccion", LessonVariant.REFORMULATE)
    assert t.pending_check_quiz_id == o.pending_check_quiz_id
    assert (t.lesson_markdown, t.last_example, t.reason) == ("## Otra", "ejemplo de dinero", "otra manera")
    assert (t.checks_on_concept, t.failures_on_concept, t.last_outcome) == (1, 1, CheckOutcome.NOT_UNDERSTOOD)
    assert t.passed_concepts == ["numero entero"]
    assert r.topic == "fraccion"
    assert [m.kind for m in r.modules] == [ModuleKind.PREREQUISITE, ModuleKind.CONTENT]


def test_una_ruta_vieja_sin_clase_se_lee_en_assessment():
    p = LearningPathAggregate.create(uuid4(), "Mate", modules=[{"concept": "suma"}])
    doc = Repo._to_doc(p)
    doc.pop("teaching")
    doc.pop("topic")
    for m in doc["modules"]:
        m.pop("kind")

    r = Repo._from_doc(doc)

    assert r.teaching.phase == TeachingPhase.ASSESSMENT and r.topic == "" and r.modules[0].kind == ModuleKind.CONTENT


def test_saltar_el_pretest_se_guarda_y_una_ruta_antigua_no_lo_tiene():
    p = LearningPathAggregate.create_for_topic(uuid4(), "python", "Python", [{"concept": "variables"}])
    assert Repo._from_doc(Repo._to_doc(p)).placement_skipped is False

    p.placement_skipped = True
    assert Repo._from_doc(Repo._to_doc(p)).placement_skipped is True

    antiguo = Repo._to_doc(p)
    del antiguo["placement_skipped"]
    assert Repo._from_doc(antiguo).placement_skipped is False
