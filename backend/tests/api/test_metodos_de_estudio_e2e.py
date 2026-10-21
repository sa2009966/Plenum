"""Elegir método y ritmo de estudio, y que se guarden en la ruta (ADR-055, fase 3).

En esta fase el método se elige, se valida, se guarda y se informa como efectivo;
cambiar cómo se arma la lección es la fase 4.
"""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.application.services.open_answer_service import OpenAnswerGradingService
from src.application.services.quiz_service import QuizService
from src.application.services.teaching_service import TeachingService
from src.application.services.topic_catalog import TopicCatalog
from src.domain import study_methods as sm
from src.domain.events.domain_events import StudyMethodChosenEvent
from src.infrastructure.config import settings
from src.infrastructure.mongodb.outbox_event_bus import _deserialize, _serialize
from src.interfaces.api import dependencies as deps
from src.main import app
from tests.api.test_preguntas_abiertas_e2e import Juez, Modelo, _auth, _respuestas
from tests.conftest import clear_dependency_caches


@pytest.fixture
def entorno(monkeypatch):
    clear_dependency_caches()
    app.dependency_overrides.clear()
    monkeypatch.setattr(settings, "STUDY_METHODS_ENABLED", True)
    monkeypatch.setattr(settings, "OPEN_QUESTIONS_ENABLED", True)
    modelo, juez = Modelo(), Juez()

    def quiz_service():
        return QuizService(
            document_repository=deps.get_document_repo(), quiz_repository=deps.get_quiz_repo(),
            attempt_repository=deps.get_attempt_repo(), interaction_repository=deps.get_interaction_repo(),
            ia_analyst=modelo, event_bus=deps.get_event_bus(), profile_repository=deps.get_profile_repo(),
            open_answer_grader=OpenAnswerGradingService(juez), open_questions_enabled=True,
        )

    app.dependency_overrides[deps.get_quiz_service] = quiz_service
    app.dependency_overrides[deps.get_teaching_service] = lambda: TeachingService(
        path_repository=deps.get_learning_path_repo(), profile_repository=deps.get_profile_repo(),
        quiz_repository=deps.get_quiz_repo(), quiz_service=quiz_service(), lesson_generator=modelo,
        topic_catalog=TopicCatalog(), attempt_repository=deps.get_attempt_repo(),
        study_methods_enabled=settings.STUDY_METHODS_ENABLED,
    )
    with TestClient(app) as c:
        yield c, modelo
    app.dependency_overrides.clear()
    clear_dependency_caches()


def _ruta(c, h, bien=True):
    quiz = c.post("/api/v1/quizzes/diagnostic", headers=h, json={"topic": "programacion"}).json()
    respuestas = _respuestas(quiz) if bien else {str(q["index"]): "no sé" for q in quiz["questions"]}
    c.post(f"/api/v1/quizzes/{quiz['id']}/attempts", headers=h, json={"answers": respuestas})
    return c.post("/api/v1/learning/paths/from-topic", headers=h, json={"topic": "programacion"}).json()


def test_apagado_no_hay_catalogo_y_el_body_se_ignora(entorno, monkeypatch):
    c, _ = entorno
    h = _auth(c)
    ruta = _ruta(c, h)
    monkeypatch.setattr(settings, "STUDY_METHODS_ENABLED", False)
    app.dependency_overrides[deps.get_teaching_service] = lambda: TeachingService(
        path_repository=deps.get_learning_path_repo(), profile_repository=deps.get_profile_repo(),
        quiz_repository=deps.get_quiz_repo(), quiz_service=deps.get_quiz_service(),
        lesson_generator=entorno[1], topic_catalog=TopicCatalog(), attempt_repository=deps.get_attempt_repo(),
    )

    r = c.get("/api/v1/learning/study-methods", headers=h)
    assert r.status_code == 404 and r.json()["reason"] == "study_methods_disabled"
    assert c.get("/api/v1/learning/me/preferences", headers=h).json()["study_methods_enabled"] is False
    c.post(f"/api/v1/learning/paths/{ruta['id']}/lesson", headers=h, json={"study_method": "feynman"})
    assert c.get(f"/api/v1/learning/paths/{ruta['id']}", headers=h).json()["study_method"] is None


def test_el_catalogo_trae_cinco_metodos_tres_ritmos_y_los_no_disponibles_con_su_texto(entorno, monkeypatch):
    c, _ = entorno
    h = _auth(c)
    monkeypatch.setattr(settings, "OPEN_QUESTIONS_ENABLED", False)

    cat = c.get("/api/v1/learning/study-methods", headers=h).json()
    claves = [m["key"] for m in cat["methods"]]
    assert claves == list(sm.METHOD_KEYS) and [p["key"] for p in cat["paces"]] == list(sm.PACE_KEYS)
    feynman = next(m for m in cat["methods"] if m["key"] == "feynman")
    assert feynman["available"] is False and feynman["unavailable_reason"] == "open_questions_disabled"
    assert feynman["unavailable_text"]
    # Sin ruta solo cuentan los interruptores: el intercalado no se juzga.
    assert next(m for m in cat["methods"] if m["key"] == "interleaving")["available"] is True
    assert not any(m["recommended"] for m in cat["methods"])
    assert cat["default_method"] is None and cat["default_pace"] == "free"


def test_por_ruta_el_intercalado_espera_y_se_recomiendan_ejemplos_en_basico(entorno):
    c, _ = entorno
    h = _auth(c)
    ruta = _ruta(c, h, bien=False)  # suspende la base: tramo básico

    cat = c.get("/api/v1/learning/study-methods", params={"path_id": ruta["id"]}, headers=h).json()
    inter = next(m for m in cat["methods"] if m["key"] == "interleaving")
    assert inter["available"] is False and inter["unavailable_reason"] == "needs_two_passed_concepts"
    recomendados = [m for m in cat["methods"] if m["recommended"]]
    assert [m["key"] for m in recomendados] == ["worked_examples"] and recomendados[0]["recommended_text"]
    assert c.get("/api/v1/learning/study-methods", params={"path_id": ruta["id"]}, headers=_auth(c)).status_code == 404


def test_las_preferencias_guardan_metodo_y_ritmo_con_merge(entorno):
    c, _ = entorno
    h = _auth(c)
    r = c.put("/api/v1/learning/me/preferences", headers=h, json={"study_method": "feynman", "study_pace": "pomodoro_25_5"})
    assert r.status_code == 200 and r.json()["study_method"] == "feynman" and r.json()["study_pace"] == "pomodoro_25_5"

    c.put("/api/v1/learning/me/preferences", headers=h, json={"explanation_style": "visual"})
    prefs = c.get("/api/v1/learning/me/preferences", headers=h).json()
    assert (prefs["study_method"], prefs["study_pace"], prefs["study_methods_enabled"]) == ("feynman", "pomodoro_25_5", True)
    c.put("/api/v1/learning/me/preferences", headers=h, json={"study_method": None})
    assert c.get("/api/v1/learning/me/preferences", headers=h).json()["study_pace"] == "pomodoro_25_5"
    assert c.put("/api/v1/learning/me/preferences", headers=h, json={"study_method": "subrayar"}).status_code == 422


def test_lo_elegido_en_la_clase_se_queda_en_la_ruta(entorno):
    c, modelo = entorno
    h = _auth(c)
    ruta = _ruta(c, h)

    r = c.post(f"/api/v1/learning/paths/{ruta['id']}/lesson", headers=h,
               json={"study_method": "worked_examples", "study_pace": "pomodoro_15_3",
                     "assessment": {"open_questions": 1, "choice_questions": 2}})
    assert r.status_code == 200
    guardada = c.get(f"/api/v1/learning/paths/{ruta['id']}", headers=h).json()
    assert (guardada["study_method"], guardada["study_pace"]) == ("worked_examples", "pomodoro_15_3")
    assert guardada["teaching"]["study_method"] == "worked_examples"
    assert sorted(modelo.lecciones[-1].check_kinds) == ["choice", "choice", "open"]

    # Responde y pide el paso siguiente SIN body: la elección y la mezcla siguen (sobreviven a recargar).
    check = r.json()["check"]
    c.post(f"/api/v1/learning/paths/{ruta['id']}/check", headers=h, json={"quiz_id": check["id"], "answers": _respuestas(check)})
    c.post(f"/api/v1/learning/paths/{ruta['id']}/lesson", headers=h)
    assert len(modelo.lecciones[-1].check_kinds) == 3
    assert c.get(f"/api/v1/learning/paths/{ruta['id']}", headers=h).json()["teaching"]["study_method"] == "worked_examples"


def test_null_devuelve_la_decision_a_laria_y_ausente_no_cambia(entorno):
    c, _ = entorno
    h = _auth(c)
    ruta = _ruta(c, h)
    c.post(f"/api/v1/learning/paths/{ruta['id']}/lesson", headers=h, json={"study_method": "elaboration", "study_pace": "pomodoro_25_5"})
    c.post(f"/api/v1/learning/paths/{ruta['id']}/lesson", headers=h, json={"study_method": None})

    guardada = c.get(f"/api/v1/learning/paths/{ruta['id']}", headers=h).json()
    assert guardada["study_method"] is None and guardada["study_pace"] == "pomodoro_25_5"


def test_un_metodo_no_disponible_es_422_con_su_motivo(entorno):
    c, _ = entorno
    h = _auth(c)
    ruta = _ruta(c, h)
    r = c.post(f"/api/v1/learning/paths/{ruta['id']}/lesson", headers=h, json={"study_method": "interleaving"})
    assert r.status_code == 422 and r.json()["reason"] == "study_method_unavailable" and r.json()["detail"]
    assert c.get(f"/api/v1/learning/paths/{ruta['id']}", headers=h).json()["study_method"] is None


def test_sin_eleccion_en_la_ruta_vale_la_preferencia(entorno):
    c, _ = entorno
    h = _auth(c)
    c.put("/api/v1/learning/me/preferences", headers=h, json={"study_method": "active_recall"})
    ruta = _ruta(c, h)
    c.post(f"/api/v1/learning/paths/{ruta['id']}/lesson", headers=h)
    guardada = c.get(f"/api/v1/learning/paths/{ruta['id']}", headers=h).json()
    assert guardada["study_method"] is None  # la ruta no eligió nada
    assert guardada["teaching"]["study_method"] == "active_recall"  # pero se aplica su preferencia


def test_si_se_apagan_las_abiertas_explicate_tu_vuelve_a_lo_de_siempre_y_lo_dice(entorno, monkeypatch):
    c, _ = entorno
    h = _auth(c)
    ruta = _ruta(c, h)
    c.put("/api/v1/learning/me/preferences", headers=h, json={"study_method": "feynman"})

    def sin_abiertas():
        servicio = deps.get_quiz_service()
        servicio.open_questions_enabled = False
        return servicio

    teaching = app.dependency_overrides[deps.get_teaching_service]
    app.dependency_overrides[deps.get_teaching_service] = lambda: _con(teaching(), sin_abiertas())
    c.post(f"/api/v1/learning/paths/{ruta['id']}/lesson", headers=h)
    t = c.get(f"/api/v1/learning/paths/{ruta['id']}", headers=h).json()["teaching"]
    assert t["study_method"] is None and "no está disponible" in t["reason"]


def _con(servicio, quiz_service):
    servicio._quiz_service = quiz_service
    return servicio


# --- Dominio ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tramo, dominio, esperado",
    [("basico", None, "worked_examples"), ("intermedio", 0.3, "worked_examples"),
     ("intermedio", None, None), ("intermedio", 0.8, None), ("avanzado", 0.1, None)],
)
def test_que_se_recomienda(tramo, dominio, esperado):
    r = sm.recommended(tramo, dominio)
    assert (r[0] if r else None) == esperado


def test_el_evento_viaja_por_el_outbox():
    e = StudyMethodChosenEvent(aggregate_id=uuid4(), student_id=uuid4(), study_method="feynman", study_pace=None)
    vuelta = _deserialize(_serialize(e))
    assert (vuelta.study_method, vuelta.study_pace, vuelta.event_id) == ("feynman", None, e.event_id)
