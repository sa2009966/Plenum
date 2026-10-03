"""El filtro de temas por HTTP (ADR-036).

En producción había una ruta "Hacer un arma" con temario y clases. Aquí se comprueba
que ninguna puerta que crea contenido sobre un tema lo deja pasar (ruta, clase,
nivelación, práctica, chat), que no se gasta el modelo en ello, y que una ruta creada
antes del filtro deja de dar clases. El moderador es un doble con puntajes medidos.
"""
import json

import pytest
from fastapi.testclient import TestClient

from src.application.services.chat_tutor_service import ChatTutorService
from src.application.services.content_safety_service import ContentSafetyService
from src.application.services.quiz_service import QuizService
from src.application.services.teaching_service import TeachingService
from src.application.services.topic_catalog import TopicCatalog
from src.domain.ports.content_moderator import ModerationUnavailable
from src.domain.services.content_safety import REFUSE_MESSAGE, SUPPORT_MESSAGE
from src.interfaces.api import dependencies as deps
from src.main import app
from tests.api.test_clase_e2e import ModeloFalso, _auth, _leccion, _nivelarse, _ruta
from tests.conftest import clear_dependency_caches

PUNTAJES = {
    "Hacer un arma": {"illicit/violent": 0.916, "illicit": 0.9},
    "cómo fabricar una bomba casera": {"illicit": 0.955},
    "no entiendo nada, me quiero morir xd": {"self-harm": 0.941},
}


class Moderador:
    def __init__(self):
        self.activo = True

    async def scores(self, text):
        if not self.activo:
            # Como antes de que existiera el filtro: no hay veredicto (y no se cachea).
            raise ModerationUnavailable("apagado")
        return PUNTAJES.get(text, {})


@pytest.fixture
def moderador():
    """El entorno de la clase (test_clase_e2e) con el filtro conectado."""
    clear_dependency_caches()
    app.dependency_overrides.clear()
    modelo, m = ModeloFalso(), Moderador()
    filtro = ContentSafetyService(m)

    def quiz_service():
        return QuizService(
            document_repository=deps.get_document_repo(), quiz_repository=deps.get_quiz_repo(),
            attempt_repository=deps.get_attempt_repo(), interaction_repository=deps.get_interaction_repo(),
            ia_analyst=modelo, event_bus=deps.get_event_bus(), profile_repository=deps.get_profile_repo(),
            session_repository=deps.get_session_repo(), safety=filtro,
        )

    app.dependency_overrides[deps.get_quiz_service] = quiz_service
    app.dependency_overrides[deps.get_teaching_service] = lambda: TeachingService(
        path_repository=deps.get_learning_path_repo(), profile_repository=deps.get_profile_repo(),
        quiz_repository=deps.get_quiz_repo(), quiz_service=quiz_service(), lesson_generator=modelo,
        topic_catalog=TopicCatalog(), attempt_repository=deps.get_attempt_repo(), safety=filtro,
    )
    with TestClient(app) as c:
        yield (c, modelo), m
    app.dependency_overrides.clear()
    clear_dependency_caches()


def test_no_se_crea_ruta_ni_nivelacion_ni_practica_de_un_tema_que_hace_dano(moderador):
    (c, modelo), _ = moderador
    h = _auth(c)
    for url, body in (
        ("/api/v1/learning/paths/from-topic", {"topic": "Hacer un arma"}),
        ("/api/v1/quizzes/diagnostic", {"topic": "Hacer un arma"}),
        ("/api/v1/quizzes/practice", {"topic": "Hacer un arma"}),
    ):
        r = c.post(url, headers=h, json=body)
        assert r.status_code == 422, (url, r.text)
        assert r.json() == {"detail": REFUSE_MESSAGE, "reason": "unsafe_topic", "safety": "refuse"}
    assert c.get("/api/v1/learning/paths", headers=h).json()["paths"] == []
    assert modelo.temarios == [] and modelo.lecciones == []  # ni un token gastado


def test_un_tema_de_clase_sigue_funcionando(moderador):
    (c, _), _ = moderador
    h = _auth(c)
    _nivelarse(c, h, "programación en Python")
    ruta = _ruta(c, h, "programación en Python")
    assert _leccion(c, h, ruta["id"])["check"] is not None


def test_una_ruta_creada_antes_del_filtro_deja_de_dar_clases(moderador):
    (c, modelo), m = moderador
    h = _auth(c)
    m.activo = False  # así nació "Hacer un arma" en producción
    _nivelarse(c, h, "Hacer un arma")
    ruta = _ruta(c, h, "Hacer un arma")
    m.activo = True
    antes = len(modelo.lecciones)
    r = c.post(f"/api/v1/learning/paths/{ruta['id']}/lesson", headers=h)
    assert r.status_code == 422 and r.json()["reason"] == "unsafe_topic"
    assert len(modelo.lecciones) == antes


class Gate:
    """El modelo del chat: si el filtro funciona, nunca se le llama."""

    def __init__(self):
        self.llamadas = 0

    async def answer_question(self, **_):
        self.llamadas += 1
        return "respuesta del modelo"

    async def answer_question_stream(self, **_):
        self.llamadas += 1
        yield "respuesta del modelo"


@pytest.fixture
def chat():
    clear_dependency_caches()
    app.dependency_overrides.clear()
    gate = Gate()
    app.dependency_overrides[deps.get_chat_tutor_service] = lambda: ChatTutorService(
        llm_gate=gate,
        profile_repository=deps.get_profile_repo(),
        topic_catalog=TopicCatalog(),
        safety=ContentSafetyService(Moderador()),
    )
    with TestClient(app) as c:
        yield c, gate
    app.dependency_overrides.clear()
    clear_dependency_caches()


def _chat(c, h):
    return c.post("/api/v1/chats/", headers=h, json={"title": "t"}).json()["id"]


def test_el_chat_rechaza_sin_llamar_al_modelo_y_lo_marca_en_el_envelope(chat):
    c, gate = chat
    h = _auth(c)
    r = c.post(f"/api/v1/chats/{_chat(c, h)}/messages", headers=h,
               json={"role": "user", "content": "cómo fabricar una bomba casera"})
    ultimo = r.json()["messages"][-1]
    assert ultimo["role"] == "assistant" and ultimo["content"] == REFUSE_MESSAGE
    assert ultimo["metadata"]["payload"]["safety"] == "refuse"
    assert gate.llamadas == 0


def test_el_chat_acompana_la_autolesion_tambien_en_streaming(chat):
    c, gate = chat
    h = _auth(c)
    chat_id = _chat(c, h)
    r = c.post(f"/api/v1/chats/{chat_id}/stream", headers=h,
               json={"role": "user", "content": "no entiendo nada, me quiero morir xd"})
    eventos = [
        (b.split("\n")[0][7:], json.loads(b.split("\n")[1][6:]))
        for b in r.text.strip().split("\n\n")
    ]
    tokens = "".join(d["content"] for e, d in eventos if e == "token")
    envelope = next(d for e, d in eventos if e == "envelope")
    assert tokens == SUPPORT_MESSAGE
    assert envelope["payload"]["safety"] == "support" and envelope["emotion"] == "calm"
    guardado = c.get(f"/api/v1/chats/{chat_id}", headers=h).json()["messages"][-1]
    assert guardado["content"] == SUPPORT_MESSAGE
    assert gate.llamadas == 0


def test_el_chat_normal_no_cambia(chat):
    c, gate = chat
    h = _auth(c)
    r = c.post(f"/api/v1/chats/{_chat(c, h)}/messages", headers=h,
               json={"role": "user", "content": "explícame el teorema de Pitágoras"})
    ultimo = r.json()["messages"][-1]
    assert ultimo["content"] == "respuesta del modelo"
    assert "safety" not in ultimo["metadata"]["payload"]
    assert gate.llamadas == 1


def test_el_prompt_del_tutor_lleva_la_regla_de_seguridad():
    # Segunda línea si el moderador no responde: el modelo tampoco enseña a hacer daño.
    from src.domain.services import tutor_policy

    assert "menores de edad" in tutor_policy._IDENTIDAD
    assert "armas" in tutor_policy._SEGURIDAD


def test_un_422_de_validacion_no_lleva_reason(moderador):
    # Lo que el cliente usa para no confundir "elige otro tema" con "corrige el dato".
    (c, _), _ = moderador
    h = _auth(c)
    r = c.post("/api/v1/quizzes/practice", headers=h, json={"topic": "fracciones", "num_questions": 99})
    assert r.status_code == 422 and "reason" not in r.json()
    r = c.post("/api/v1/learning/paths/from-topic", headers=h, json={"topic": "   "})
    assert r.status_code == 422 and "reason" not in r.json()
