"""Un fallo del proveedor durante el streaming queda en el log y se explica bien.

El endpoint SSE convertía cualquier excepción en «No pude generar la respuesta» sin
registrar nada: en Render no quedaba rastro de qué falló, y un 429 (saturado, basta
con esperar) se veía igual que un error de verdad.
"""
import logging

import pytest
from fastapi.testclient import TestClient

from src.application.services.chat_tutor_service import ChatTutorService
from src.domain.ports.ia_analyst import IAAnalysisError
from src.infrastructure.ia.base_chat_analyst import _MSG_SATURADO
from src.interfaces.api import dependencies as deps
from src.main import app
from tests.api.test_clase_e2e import _auth
from tests.conftest import clear_dependency_caches


class GateQueFalla:
    def __init__(self, error):
        self._error = error

    async def answer_question(self, **kw):
        raise self._error

    async def answer_question_stream(self, **kw):
        raise self._error
        yield  # pragma: no cover — lo convierte en generador


@pytest.fixture
def cliente():
    def _con(error):
        clear_dependency_caches()
        app.dependency_overrides.clear()
        app.dependency_overrides[deps.get_chat_tutor_service] = lambda: ChatTutorService(
            llm_gate=GateQueFalla(error), profile_repository=deps.get_profile_repo(),
            event_bus=deps.get_event_bus(),
        )
        return TestClient(app)

    yield _con
    app.dependency_overrides.clear()
    clear_dependency_caches()


def _preguntar(c):
    h = _auth(c)
    chat_id = c.post("/api/v1/chats", headers=h, json={}).json()["id"]
    r = c.post(f"/api/v1/chats/{chat_id}/stream", headers=h, json={"role": "user", "content": "¿Qué es un bucle?"})
    assert r.status_code == 200
    return r.text


def test_con_el_proveedor_saturado_se_dice_que_espere(cliente, caplog):
    with cliente(IAAnalysisError(_MSG_SATURADO)) as c, caplog.at_level(logging.ERROR):
        cuerpo = _preguntar(c)

    assert "event: error" in cuerpo and "muchas peticiones" in cuerpo
    assert "chat_stream_fallo" in caplog.text


def test_un_fallo_interno_queda_en_el_log_sin_detalles_para_el_estudiante(cliente, caplog):
    with cliente(RuntimeError("detalle interno")) as c, caplog.at_level(logging.ERROR):
        cuerpo = _preguntar(c)

    assert "No pude generar la respuesta" in cuerpo and "detalle interno" not in cuerpo
    assert "chat_stream_fallo" in caplog.text and "RuntimeError" in caplog.text
