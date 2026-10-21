"""La clase avanza igual con el outbox de producción que con el bus en memoria.

Informe de error: al terminar un tema, la clase volvía a presentar el MISMO tema en
vez de pasar al siguiente de la guía. En producción el bus es el outbox de Mongo:
`publish` solo guarda el evento y el worker lo proyecta al perfil después. Al
decidir el siguiente paso, la clase releía el perfil suponiendo que el projector
ya había aplicado la comprobación recién respondida; con el outbox aún no, así que
decidía con el dominio de ANTES de responder y pedía «afianzar» el tema superado.

Aquí el bus difiere los eventos como el outbox: se proyectan entre peticiones
(como haría el worker), nunca dentro de la petición que los publica.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

from src.application.services.quiz_service import QuizService
from src.application.services.teaching_service import TeachingService
from src.application.services.topic_catalog import TopicCatalog
from src.interfaces.api import dependencies as deps
from src.main import app
from tests.api.test_clase_e2e import ModeloFalso, _auth, _correctas
from tests.conftest import clear_dependency_caches


class BusDiferido:
    """Como el outbox: publicar guarda; el «worker» (`proyectar`) entrega después."""

    def __init__(self, real):
        self._real = real
        self._pendientes = []

    async def publish(self, event):
        self._pendientes.append(event)

    async def subscribe(self, event_type, handler):
        await self._real.subscribe(event_type, handler)

    def proyectar(self):
        pendientes, self._pendientes = self._pendientes, []
        for evento in pendientes:
            asyncio.run(self._real.publish(evento))


@pytest.fixture
def entorno_outbox():
    clear_dependency_caches()
    app.dependency_overrides.clear()
    modelo = ModeloFalso()
    bus = BusDiferido(deps.get_event_bus())

    def quiz_service():
        return QuizService(
            document_repository=deps.get_document_repo(), quiz_repository=deps.get_quiz_repo(),
            attempt_repository=deps.get_attempt_repo(), interaction_repository=deps.get_interaction_repo(),
            ia_analyst=modelo, event_bus=bus, profile_repository=deps.get_profile_repo(),
            session_repository=deps.get_session_repo(),
        )

    app.dependency_overrides[deps.get_quiz_service] = quiz_service
    app.dependency_overrides[deps.get_teaching_service] = lambda: TeachingService(
        path_repository=deps.get_learning_path_repo(), profile_repository=deps.get_profile_repo(),
        quiz_repository=deps.get_quiz_repo(), quiz_service=quiz_service(), lesson_generator=modelo,
        topic_catalog=TopicCatalog(), attempt_repository=deps.get_attempt_repo(),
    )
    with TestClient(app) as c:
        yield c, bus
    app.dependency_overrides.clear()
    clear_dependency_caches()


def _recorrer(c, h, bus, path_id):
    """Acierta cada comprobación; el worker proyecta entre una petición y la siguiente."""
    vistos = []
    for _ in range(8):
        r = c.post(f"/api/v1/learning/paths/{path_id}/lesson", headers=h)
        assert r.status_code == 200, r.text
        paso = r.json()
        if paso["check"] is None:
            return vistos, paso["path"]
        vistos.append((paso["path"]["teaching"]["concept"], paso["path"]["teaching"]["variant"]))
        r = c.post(f"/api/v1/learning/paths/{path_id}/check", headers=h,
                   json={"quiz_id": paso["check"]["id"], "answers": _correctas(paso["check"])})
        assert r.status_code == 200, r.text
        bus.proyectar()
    raise AssertionError("la ruta no terminó")


def test_superar_un_tema_con_el_outbox_pasa_al_siguiente_sin_repetirlo(entorno_outbox):
    c, bus = entorno_outbox
    h = _auth(c)
    q = c.post("/api/v1/quizzes/diagnostic", headers=h, json={"topic": "python"}).json()
    c.post(f"/api/v1/quizzes/{q['id']}/attempts", headers=h, json={"answers": _correctas(q)})
    bus.proyectar()
    ruta = c.post("/api/v1/learning/paths/from-topic", headers=h, json={"topic": "python"}).json()

    vistos, final = _recorrer(c, h, bus, ruta["id"])

    # Lo mismo que con el bus en memoria (test_ruta_completa_paso_a_paso_...): cada
    # tema una vez, en orden, sin «afianzar» uno que ya se superó.
    assert vistos == [("variables", "introduce"), ("bucles", "introduce")]
    assert final["teaching"]["phase"] == "completed"
