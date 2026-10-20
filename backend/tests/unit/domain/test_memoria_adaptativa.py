"""La vida media de cada concepto se ajusta con los repasos calificados (ADR-051).

Antes era 14 días para todo y para todos: el sistema "sabía" que se olvida, pero no
aprendía de cada estudiante cuánto tarda en olvidar cada cosa.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from src.domain import memory_model as mm
from src.domain.aggregates.student_profile import ConceptMastery, StudentProfile
from src.infrastructure.mongodb.student_profile_repository import MongoDBStudentProfileRepository

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


def test_el_intervalo_sale_de_la_retencion_objetivo():
    # 0,5 ** (t / 14) = 0,9  →  t = 14 · log2(1/0,9) ≈ 2,13 días
    assert mm.interval_days(14.0, 0.9) == pytest.approx(2.128, abs=0.01)
    assert mm.retention(14.0, 14.0) == pytest.approx(0.5)
    assert mm.next_review_at(T0, 14.0, 0.5) == T0 + timedelta(days=14)


def test_repetir_en_bloque_no_consolida_y_espaciar_si():
    h = 10.0
    en_bloque = mm.next_half_life(h, elapsed_days=0.0, score_ratio=1.0)
    espaciado = mm.next_half_life(h, elapsed_days=10.0, score_ratio=1.0)  # se esperaba recordar el 50 %

    assert en_bloque == pytest.approx(h)
    assert espaciado == pytest.approx(h * 2.5)


def test_fallar_acorta_y_fallar_en_blanco_acorta_mas():
    assert mm.next_half_life(10.0, 5.0, 0.0) == pytest.approx(3.0)
    assert mm.next_half_life(10.0, 5.0, 0.4) == pytest.approx(5.0)


def test_la_vida_media_tiene_suelo_y_techo():
    assert mm.next_half_life(1.0, 0.5, 0.0) == mm.MIN_HALF_LIFE_DAYS
    assert mm.next_half_life(300.0, 600.0, 1.0) == mm.MAX_HALF_LIFE_DAYS


def test_un_quiz_es_un_repaso_por_concepto_no_uno_por_pregunta():
    perfil = StudentProfile.create(uuid4())
    perfil.record_diagnostic_result(
        concept_results=(("Fracción", 1.0), ("fraccion", 1.0), ("fracción", 0.0), ("suma", 1.0)),
        at=T0,
    )

    fraccion = perfil.mastery_by_concept["fraccion"]
    assert len(fraccion.review_log) == 1
    assert fraccion.review_log[0].score_ratio == pytest.approx(2 / 3)
    assert fraccion.last_reviewed_at == T0
    assert fraccion.half_life_days == pytest.approx(mm.first_half_life(2 / 3))
    assert len(perfil.mastery_by_concept["suma"].review_log) == 1


def test_el_segundo_repaso_usa_el_tiempo_transcurrido():
    perfil = StudentProfile.create(uuid4())
    perfil.record_diagnostic_result(concept_results=(("suma", 1.0),), at=T0)
    h1 = perfil.mastery_by_concept["suma"].half_life_days
    perfil.record_diagnostic_result(concept_results=(("suma", 1.0),), at=T0 + timedelta(days=h1))

    c = perfil.mastery_by_concept["suma"]
    assert c.half_life_days == pytest.approx(h1 * 2.5)
    assert [e.half_life_days for e in c.review_log] == [pytest.approx(h1), pytest.approx(h1 * 2.5)]


def test_el_chat_no_es_un_repaso():
    """Invariante 4: decir "no entiendo" es información, no una medición de memoria."""
    perfil = StudentProfile.create(uuid4())
    perfil.record_ask_struggle(uuid4(), concepts=("suma",))

    c = perfil.mastery_by_concept["suma"]
    assert c.review_log == [] and c.last_reviewed_at is None


def test_la_curva_vuelve_a_uno_en_cada_repaso_y_cae_con_su_vida_media():
    log_ = [
        mm.ReviewEntry(at=T0, score_ratio=1.0, half_life_days=5.0),
        mm.ReviewEntry(at=T0 + timedelta(days=5), score_ratio=1.0, half_life_days=12.0),
    ]
    puntos = mm.estimated_curve(log_, until=T0 + timedelta(days=17))

    assert len(puntos) <= mm.MAX_CURVE_POINTS
    assert [t for t, _ in puntos] == sorted(t for t, _ in puntos)
    assert puntos[0] == (T0, 1.0)
    antes_del_segundo = max(r for t, r in puntos if t == T0 + timedelta(days=5) and r < 1.0)
    assert antes_del_segundo == pytest.approx(0.5)  # 5 días con vida media de 5
    assert puntos[-1][1] == pytest.approx(0.5)  # 12 días con vida media de 12


def test_con_muchos_repasos_la_curva_no_pasa_de_60_puntos():
    log_ = [mm.ReviewEntry(at=T0 + timedelta(days=i), score_ratio=1.0, half_life_days=3.0) for i in range(30)]
    puntos = mm.estimated_curve(log_, until=T0 + timedelta(days=40))
    assert 0 < len(puntos) <= 60
    assert puntos[-1][0] == T0 + timedelta(days=40)


def test_el_historial_sobrevive_a_mongo_y_vuelve_con_zona():
    perfil = StudentProfile.create(uuid4())
    perfil.record_diagnostic_result(concept_results=(("suma", 0.5),), at=T0)
    doc = MongoDBStudentProfileRepository._to_doc(perfil, 1)
    # Mongo devuelve las fechas sin zona.
    crudo = doc["mastery_by_concept"]["suma"]
    crudo["last_reviewed_at"] = crudo["last_reviewed_at"].replace(tzinfo=None)
    crudo["review_log"][0]["at"] = crudo["review_log"][0]["at"].replace(tzinfo=None)

    c = MongoDBStudentProfileRepository._from_doc(doc).mastery_by_concept["suma"]
    assert c.last_reviewed_at == T0 and c.review_log[0].at == T0
    assert c.review_log[0].score_ratio == 0.5


def test_un_perfil_anterior_no_inventa_historial():
    doc = MongoDBStudentProfileRepository._to_doc(StudentProfile.create(uuid4()), 1)
    doc["mastery_by_concept"] = {"suma": {"concept_key": "suma", "attempts": 3, "mastery": 0.8}}

    c = MongoDBStudentProfileRepository._from_doc(doc).mastery_by_concept["suma"]
    assert c.review_log == [] and c.last_reviewed_at is None and c.half_life_days == 14.0


def test_concept_mastery_sin_repasos_conserva_la_vida_media_inicial():
    assert ConceptMastery(concept_key="x").half_life_days == mm.INITIAL_HALF_LIFE_DAYS
