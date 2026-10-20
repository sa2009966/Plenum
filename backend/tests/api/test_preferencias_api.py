"""PUT /learning/me/preferences: elegir cómo quiero que me expliquen (ADR-022).

Desde el ADR-053 la respuesta trae también `assessment` (la mezcla de preguntas) y el
PUT es merge: aquí se comprueba solo lo del estilo; la mezcla, en
`test_preguntas_abiertas_e2e.py`.
"""
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.domain.events.domain_events import ExplanationStyleChosenEvent
from src.infrastructure.mongodb.outbox_event_bus import _deserialize, _serialize
from src.main import app
from tests.conftest import clear_dependency_caches


@pytest.fixture
def client():
    clear_dependency_caches()
    with TestClient(app) as c:
        yield c
    clear_dependency_caches()


def _auth(c):
    s = uuid4().hex[:8]
    email = f"pref_{s}@example.com"
    c.post("/api/v1/auth/register", json={"username": f"pref_{s}", "email": email, "password": "SecurePass1x"})
    tok = c.post("/api/v1/auth/token", data={"username": email, "password": "SecurePass1x"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def test_elegir_un_estilo_se_ve_en_preferencias_y_en_el_perfil(client):
    h = _auth(client)

    r = client.put("/api/v1/learning/me/preferences", headers=h, json={"explanation_style": "analogy"})

    assert r.status_code == 200 and r.json()["explanation_style"] == "analogy"
    assert client.get("/api/v1/learning/me/preferences", headers=h).json()["explanation_style"] == "analogy"
    assert client.get("/api/v1/learning/me/profile", headers=h).json()["explanation_style_choice"] == "analogy"


def test_null_devuelve_la_decision_a_laria(client):
    h = _auth(client)
    client.put("/api/v1/learning/me/preferences", headers=h, json={"explanation_style": "visual"})

    r = client.put("/api/v1/learning/me/preferences", headers=h, json={"explanation_style": None})

    assert r.json()["explanation_style"] is None
    assert client.get("/api/v1/learning/me/profile", headers=h).json()["explanation_style_choice"] is None


def test_sin_elegir_nada_es_null(client):
    h = _auth(client)

    assert client.get("/api/v1/learning/me/preferences", headers=h).json()["explanation_style"] is None


def test_un_estilo_desconocido_es_422(client):
    h = _auth(client)

    assert client.put("/api/v1/learning/me/preferences", headers=h, json={"explanation_style": "escuchando"}).status_code == 422


def test_un_estilo_ausente_no_borra_el_elegido(client):
    """Antes un body sin estilo era 422. Con el merge del ADR-053 es «no cambiar»: si no,
    la pantalla que guarda la mezcla de preguntas borraría el estilo elegido."""
    h = _auth(client)
    client.put("/api/v1/learning/me/preferences", headers=h, json={"explanation_style": "visual"})

    r = client.put("/api/v1/learning/me/preferences", headers=h, json={})

    assert r.status_code == 200 and r.json()["explanation_style"] == "visual"


def test_sin_sesion_es_401(client):
    assert client.put("/api/v1/learning/me/preferences", json={"explanation_style": "visual"}).status_code == 401


@pytest.mark.parametrize("estilo", ["step_by_step", None])
def test_el_evento_sobrevive_al_outbox(estilo):
    """Producción puede usar el outbox: un evento que no viaje dejaría la elección muerta solo ahí."""
    uid = uuid4()
    e = ExplanationStyleChosenEvent(aggregate_id=uid, student_id=uid, style=estilo)
    p = _serialize(e)

    leido = _deserialize({"event_type": p["event_type"], "payload": p})

    assert isinstance(leido, ExplanationStyleChosenEvent)
    assert leido.style == estilo and leido.student_id == uid and leido.event_id == e.event_id


@pytest.mark.asyncio
async def test_el_projector_aplica_la_eleccion_una_sola_vez():
    from src.application.services.learning_evidence_projector import LearningEvidenceProjector
    from src.infrastructure.persistence.in_memory_student_profile_repo import (
        InMemoryStudentProfileRepository,
    )

    repo = InMemoryStudentProfileRepository()
    projector = LearningEvidenceProjector.__new__(LearningEvidenceProjector)
    projector._profile_repo = repo
    uid = uuid4()
    e = ExplanationStyleChosenEvent(aggregate_id=uid, student_id=uid, style="visual")

    await projector.handle_style_chosen(e)
    await projector.handle_style_chosen(e)

    perfil = await repo.find_by_student(uid)
    assert perfil.explanation_style_choice == "visual"
    assert perfil.applied_event_ids.count(str(e.event_id)) == 1
