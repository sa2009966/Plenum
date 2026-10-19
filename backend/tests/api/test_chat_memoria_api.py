"""El router le pasa al tutor lo que ya estaba guardado en el chat.

Los mensajes se persistían desde el principio y el tutor no los leía nunca: el
espacio en la base existía, lo que faltaba era usarlo.
"""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.domain.ports.embodiment import AffectState
from src.domain.services.response_envelope import ResponseEnvelope
from src.interfaces.api import dependencies as deps
from src.main import app
from tests.conftest import clear_dependency_caches


class TutorQueRecuerda:
    """Doble que anota qué historial recibió en cada turno."""

    def __init__(self):
        self.historiales: list[tuple] = []

    async def answer(self, document_id, question, student_id, history=()):
        from src.application.services.chat_tutor_service import TutorResponse

        self.historiales.append(history)
        return TutorResponse(
            content=f"eco: {question}",
            envelope=ResponseEnvelope(type="answer", emotion=AffectState.ENCOURAGING, payload={"content": "x"}),
        )

    async def answer_stream(self, document_id, question, student_id, history=()):
        self.historiales.append(history)
        yield "eco", None
        yield "eco", ResponseEnvelope(type="answer", emotion=AffectState.ENCOURAGING, payload={"content": "eco"})


@pytest.fixture
def client_y_tutor():
    clear_dependency_caches()
    tutor = TutorQueRecuerda()
    app.dependency_overrides[deps.get_chat_tutor_service] = lambda: tutor
    with TestClient(app) as c:
        yield c, tutor
    app.dependency_overrides.clear()
    clear_dependency_caches()


def _auth(c: TestClient) -> dict:
    s = uuid4().hex[:8]
    email = f"mem_{s}@example.com"
    c.post("/api/v1/auth/register", json={"username": f"mem_{s}", "email": email, "password": "SecurePass1x"})
    tok = c.post("/api/v1/auth/token", data={"username": email, "password": "SecurePass1x"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def test_el_segundo_turno_recibe_el_primero(client_y_tutor):
    c, tutor = client_y_tutor
    h = _auth(c)
    chat = c.post("/api/v1/chats/", headers=h, json={}).json()["id"]

    c.post(f"/api/v1/chats/{chat}/messages", headers=h, json={"role": "user", "content": "me llamo Alex"})
    c.post(f"/api/v1/chats/{chat}/messages", headers=h, json={"role": "user", "content": "¿cómo me llamo?"})

    assert tutor.historiales[0] == (), "el primer mensaje no tiene nada detrás"
    assert tutor.historiales[1] == (("user", "me llamo Alex"), ("assistant", "eco: me llamo Alex"))


def test_el_historial_no_incluye_el_mensaje_actual(client_y_tutor):
    """Si lo incluyera, el modelo vería la pregunta dos veces."""
    c, tutor = client_y_tutor
    h = _auth(c)
    chat = c.post("/api/v1/chats/", headers=h, json={}).json()["id"]

    c.post(f"/api/v1/chats/{chat}/messages", headers=h, json={"role": "user", "content": "primera"})
    c.post(f"/api/v1/chats/{chat}/messages", headers=h, json={"role": "user", "content": "segunda"})

    assert all(texto != "segunda" for _, texto in tutor.historiales[1])


def test_el_streaming_tambien_recuerda(client_y_tutor):
    c, tutor = client_y_tutor
    h = _auth(c)
    chat = c.post("/api/v1/chats/", headers=h, json={}).json()["id"]

    c.post(f"/api/v1/chats/{chat}/messages", headers=h, json={"role": "user", "content": "me llamo Alex"})
    with c.stream("POST", f"/api/v1/chats/{chat}/stream", headers=h, json={"role": "user", "content": "¿y ahora?"}) as r:
        r.read()

    assert ("user", "me llamo Alex") in tutor.historiales[-1]


class ResumidorFalso:
    def __init__(self):
        self.llamadas = 0

    async def summarize_conversation(self, previous, messages):
        self.llamadas += 1
        return f"{previous} | {len(messages)} mensajes, primero: {messages[0][1]}".strip(" |")


@pytest.mark.parametrize("ruta", ["messages", "stream"])
def test_un_chat_largo_llega_con_resumen_y_se_guarda(client_y_tutor, ruta):
    """ADR-021: el dato del primer mensaje sigue llegando 25 mensajes después."""
    from src.application.services.conversation_memory import ConversationMemory
    from src.domain.aggregates.chat import HISTORY_MAX_MESSAGES, SUMMARY_BATCH

    c, tutor = client_y_tutor
    resumidor = ResumidorFalso()
    app.dependency_overrides[deps.get_conversation_memory] = lambda: ConversationMemory(resumidor)
    h = _auth(c)
    chat_id = c.post("/api/v1/chats", headers=h, json={}).json()["id"]

    turnos = (HISTORY_MAX_MESSAGES + SUMMARY_BATCH) // 2 + 1
    for i in range(turnos):
        texto = "me llamo Ana" if i == 0 else f"pregunta {i}"
        r = c.post(f"/api/v1/chats/{chat_id}/{ruta}", headers=h, json={"role": "user", "content": texto})
        assert r.status_code == 200

    assert resumidor.llamadas == 1
    ultimo = tutor.historiales[-1]
    assert ultimo[0][0] == "resumen" and "me llamo Ana" in ultimo[0][1]

    import asyncio
    from uuid import UUID
    guardado = asyncio.run(deps.get_chat_repo().find_by_id(UUID(chat_id)))
    assert guardado.summary_upto == SUMMARY_BATCH
    assert "me llamo Ana" in guardado.summary


class TutorQueDibuja:
    """Los tokens traen un esquema con enlace; el cierre del servicio, ya sin él."""

    async def answer_stream(self, document_id, question, student_id, history=()):
        yield "Mira:\n```mermaid\nflowchart TD\n  A --> B\n  click A \"https://x\"\n```", None
        yield "Mira:", ResponseEnvelope(type="answer", emotion=AffectState.ENCOURAGING, payload={"content": "Mira:"})


def test_tras_el_streaming_se_guarda_el_texto_del_cierre_no_los_tokens():
    """ADR-048: el esquema que no se puede pintar no debe quedar en el historial."""
    clear_dependency_caches()
    app.dependency_overrides[deps.get_chat_tutor_service] = lambda: TutorQueDibuja()
    try:
        with TestClient(app) as c:
            h = _auth(c)
            chat = c.post("/api/v1/chats/", headers=h, json={}).json()
            c.post(f"/api/v1/chats/{chat['id']}/stream", headers=h, json={"role": "user", "content": "dibújalo"})
            mensajes = c.get(f"/api/v1/chats/{chat['id']}", headers=h).json()["messages"]
            assert mensajes[-1]["role"] == "assistant" and mensajes[-1]["content"] == "Mira:"
    finally:
        app.dependency_overrides.clear()
        clear_dependency_caches()
