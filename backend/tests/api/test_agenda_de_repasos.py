"""Agenda de repasos y curva del olvido, de punta a punta (ADR-051).

Un repaso nace de un intento calificado (aquí, una nivelación), lo aplica el
projector y la agenda lo lee. Nada se inventa: sin evidencia, la agenda está vacía.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from src.application.services.review_service import ConceptWithoutReviews, ReviewScheduleService
from src.domain.aggregates.learning_path import LearningPathAggregate
from src.domain.aggregates.student_profile import StudentProfile
from src.infrastructure.persistence.in_memory_learning_path_repo import InMemoryLearningPathRepository
from src.infrastructure.persistence.in_memory_student_profile_repo import InMemoryStudentProfileRepository
from tests.api.test_diagnostico_e2e import _auth, _pedir, _responder, client, todas  # noqa: F401

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


def test_sin_evidencia_la_forma_es_la_misma_y_vacia(client):
    headers, _ = _auth(client)
    r = client.get("/api/v1/learning/me/reviews", headers=headers)

    assert r.status_code == 200
    assert r.json()["counts"] == {"overdue": 0, "today": 0, "upcoming": 0}
    assert r.json()["items"] == []
    assert client.get("/api/v1/learning/me/reviews/curve", params={"concept": "suma"}, headers=headers).status_code == 404


def test_una_nivelacion_agenda_sus_conceptos_y_dibuja_su_curva(client):
    headers, _ = _auth(client)
    _responder(client, headers, _pedir(client, headers), todas)

    agenda = client.get("/api/v1/learning/me/reviews", params={"tz": "Europe/Madrid"}, headers=headers).json()
    assert agenda["items"], "la nivelación es evidencia calificada: debe agendarse"
    item = agenda["items"][0]
    assert item["reviews"] == 1 and item["status"] == "upcoming"
    assert item["estimated_retention"] == pytest.approx(1.0, abs=0.01)
    assert item["next_review_at"].endswith(("Z", "+00:00"))
    assert sum(agenda["counts"].values()) == len(agenda["items"])

    curva = client.get(
        "/api/v1/learning/me/reviews/curve", params={"concept": item["concept"]}, headers=headers
    ).json()
    assert len(curva["measured"]) == 1 and curva["measured"][0]["score_ratio"] == 1.0
    assert 0 < len(curva["estimated"]) <= 60
    assert curva["estimated"][0]["retention"] == 1.0
    assert [p["at"] for p in curva["estimated"]] == sorted(p["at"] for p in curva["estimated"])
    assert "Estimación" in curva["note"]


def test_limit_recorta_la_lista_pero_no_los_totales(client):
    headers, _ = _auth(client)
    _responder(client, headers, _pedir(client, headers), todas)

    todo = client.get("/api/v1/learning/me/reviews", headers=headers).json()
    uno = client.get("/api/v1/learning/me/reviews", params={"limit": 1}, headers=headers).json()
    assert len(uno["items"]) == 1
    assert uno["counts"] == todo["counts"]
    assert client.get("/api/v1/learning/me/reviews", params={"limit": 0}, headers=headers).status_code == 422


def test_la_agenda_es_de_quien_trae_el_token(client):
    headers_a, _ = _auth(client)
    _responder(client, headers_a, _pedir(client, headers_a), todas)
    headers_b, _ = _auth(client)

    assert client.get("/api/v1/learning/me/reviews", headers=headers_b).json()["items"] == []


def test_sin_token_es_401(client):
    assert client.get("/api/v1/learning/me/reviews").status_code == 401


# --- El servicio, con el reloj en la mano -------------------------------------------


async def _servicio(perfil: StudentProfile, rutas=()) -> ReviewScheduleService:
    perfiles = InMemoryStudentProfileRepository()
    await perfiles.save(perfil)
    caminos = InMemoryLearningPathRepository()
    for r in rutas:
        await caminos.save(r)
    return ReviewScheduleService(perfiles, caminos, desired_retention=0.9)


@pytest.mark.asyncio
async def test_vencido_hoy_y_proximo_se_cuentan_con_el_dia_local():
    perfil = StudentProfile.create(uuid4())
    perfil.record_diagnostic_result(concept_results=(("suma", 1.0),), at=T0)
    proximo = T0 + timedelta(days=21 * 0.152)  # vida media 21 → ~3,2 días
    servicio = await _servicio(perfil)

    antes = await servicio.agenda(perfil.student_id, now=proximo - timedelta(days=2))
    assert antes.items[0].status == "upcoming"
    # A las 23:30 UTC del día del repaso, en Madrid ya es el día siguiente: vencido.
    tarde = proximo.replace(hour=23, minute=30)
    assert (await servicio.agenda(perfil.student_id, tz="UTC", now=tarde)).items[0].status == "today"
    assert (await servicio.agenda(perfil.student_id, tz="Europe/Madrid", now=tarde)).items[0].status == "overdue"
    assert (await servicio.agenda(perfil.student_id, tz="No/Existe", now=tarde)).items[0].status == "today"


@pytest.mark.asyncio
async def test_primero_lo_mas_olvidado_y_el_enlace_a_su_ruta():
    perfil = StudentProfile.create(uuid4())
    perfil.record_diagnostic_result(concept_results=(("suma", 1.0), ("resta", 0.0)), at=T0)
    ruta = LearningPathAggregate.create(
        owner_id=perfil.student_id, subject="Matemáticas", title="Aritmética", modules=[{"title": "Resta", "concept": "resta"}]
    )
    servicio = await _servicio(perfil, [ruta])

    agenda = await servicio.agenda(perfil.student_id, now=T0 + timedelta(days=30))
    assert [i.concept for i in agenda.items] == ["resta", "suma"]  # resta: vida media de 7 días, más olvidada
    assert agenda.items[0].path_id == ruta.id and agenda.items[0].label == "Resta"
    assert agenda.items[1].path_id is None


@pytest.mark.asyncio
async def test_un_perfil_anterior_con_evidencia_calificada_aparece_sin_repasos():
    perfil = StudentProfile.create(uuid4())
    perfil.record_concept_result("suma", 1.0)
    c = perfil.mastery_by_concept["suma"]
    c.last_reviewed_at, c.review_log = None, []  # como un perfil escrito antes del ADR-051
    servicio = await _servicio(perfil)

    agenda = await servicio.agenda(perfil.student_id)
    assert agenda.items[0].reviews == 0 and agenda.items[0].half_life_days == 14.0
    curva = await servicio.curve(perfil.student_id, "Suma")
    assert curva.measured == [] and curva.estimated


@pytest.mark.asyncio
async def test_lo_que_solo_se_pregunto_en_el_chat_no_se_agenda():
    perfil = StudentProfile.create(uuid4())
    perfil.record_ask_struggle(uuid4(), concepts=("suma",))
    servicio = await _servicio(perfil)

    assert (await servicio.agenda(perfil.student_id)).items == []
    with pytest.raises(ConceptWithoutReviews):
        await servicio.curve(perfil.student_id, "suma")
