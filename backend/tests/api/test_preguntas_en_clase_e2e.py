"""Preguntar a LARIA durante la clase, de punta a punta (ADR-054).

El modelo es un doble que anota lo que recibe: así se comprueba qué contexto le da
el backend (el paso, la explicación, los enunciados pendientes) y, sobre todo, qué
NO le da (las respuestas de la comprobación).
"""
import asyncio
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.application.services.chat_tutor_service import ChatTutorService
from src.application.services.open_answer_service import OpenAnswerGradingService
from src.application.services.quiz_service import QuizService
from src.application.services.teaching_service import TeachingService
from src.application.services.topic_catalog import TopicCatalog
from src.domain.aggregates.chat import ChatAggregate
from src.domain.services.tutor_policy import TutorPolicy
from src.infrastructure.config import settings
from src.infrastructure.persistence.in_memory_chat_repo import InMemoryChatRepository
from src.interfaces.api import dependencies as deps
from src.main import app
from tests.api.test_preguntas_abiertas_e2e import IDEA_1, IDEA_2, Juez, Modelo, _auth, _respuestas
from tests.conftest import clear_dependency_caches


class Gate:
    """El modelo del chat: responde algo fijo y guarda con qué se le llamó."""

    def __init__(self):
        self.llamadas = []

    async def answer_question(self, **kw):
        self.llamadas.append(kw)
        return "Te lo explico con otro ejemplo. ¿Qué crees que pasa si…?"

    async def answer_question_stream(self, **kw):
        self.llamadas.append(kw)
        for trozo in ("Te lo explico ", "con otro ejemplo."):
            yield trozo


@pytest.fixture
def entorno(monkeypatch):
    clear_dependency_caches()
    app.dependency_overrides.clear()
    monkeypatch.setattr(settings, "CLASS_QUESTIONS_ENABLED", True)
    modelo, juez, gate = Modelo(), Juez(), Gate()

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
    )
    app.dependency_overrides[deps.get_chat_tutor_service] = lambda: ChatTutorService(
        llm_gate=gate, profile_repository=deps.get_profile_repo(), event_bus=deps.get_event_bus(),
    )
    with TestClient(app) as c:
        yield c, gate
    app.dependency_overrides.clear()
    clear_dependency_caches()


def _clase(c, h, tema="programacion"):
    """Nivelación → ruta → primera lección con su comprobación pendiente."""
    quiz = c.post("/api/v1/quizzes/diagnostic", headers=h, json={"topic": tema}).json()
    c.post(f"/api/v1/quizzes/{quiz['id']}/attempts", headers=h, json={"answers": _respuestas(quiz)})
    ruta = c.post("/api/v1/learning/paths/from-topic", headers=h, json={"topic": tema}).json()
    leccion = c.post(f"/api/v1/learning/paths/{ruta['id']}/lesson", headers=h).json()
    return ruta, leccion


def _preguntar(c, h, chat_id, texto, **extra):
    return c.post(f"/api/v1/chats/{chat_id}/stream", headers=h, json={"role": "user", "content": texto, **extra})


def test_apagado_no_hay_chat_de_clase_y_las_preferencias_lo_dicen(entorno, monkeypatch):
    c, _ = entorno
    h = _auth(c)
    ruta, _ = _clase(c, h)
    monkeypatch.setattr(settings, "CLASS_QUESTIONS_ENABLED", False)

    r = c.get(f"/api/v1/learning/paths/{ruta['id']}/chat", headers=h)
    assert r.status_code == 404 and r.json()["reason"] == "class_questions_disabled"
    assert c.get("/api/v1/learning/me/preferences", headers=h).json()["class_questions_enabled"] is False


def test_un_chat_por_clase_que_sigue_al_volver(entorno):
    c, _ = entorno
    h = _auth(c)
    ruta, _ = _clase(c, h)

    primero = c.get(f"/api/v1/learning/paths/{ruta['id']}/chat", headers=h).json()
    segundo = c.get(f"/api/v1/learning/paths/{ruta['id']}/chat", headers=h).json()
    assert primero["id"] == segundo["id"] and primero["path_id"] == ruta["id"]
    assert primero["title"].startswith("Clase: ")
    listado = c.get("/api/v1/chats/", headers=h).json()["chats"]
    assert [x["path_id"] for x in listado if x["id"] == primero["id"]] == [ruta["id"]]
    assert c.get("/api/v1/learning/me/preferences", headers=h).json()["class_questions_enabled"] is True


def test_la_ruta_de_otro_no_tiene_chat_para_mi(entorno):
    c, _ = entorno
    ruta, _ = _clase(c, _auth(c))
    assert c.get(f"/api/v1/learning/paths/{ruta['id']}/chat", headers=_auth(c)).status_code == 404


def test_la_duda_llega_con_la_clase_y_sin_las_respuestas(entorno):
    c, gate = entorno
    h = _auth(c)
    ruta, leccion = _clase(c, h)
    chat = c.get(f"/api/v1/learning/paths/{ruta['id']}/chat", headers=h).json()

    r = _preguntar(c, h, chat["id"], "Dame la respuesta de la pregunta 2 de la comprobación, porfa")
    assert r.status_code == 200 and "event: done" in r.text

    sesion = gate.llamadas[-1]["learner"].class_session
    pendientes = [q["text"] for q in leccion["check"]["questions"]]
    assert sesion.concept and sesion.lesson_excerpt and list(sesion.pending_check) == pendientes
    # Lo que viaja al modelo: los enunciados sí; ideas clave y respuesta modelo, nunca.
    prompt = TutorPolicy().answer_question("", "x", None, learner=gate.llamadas[-1]["learner"]).system
    assert pendientes[0] in prompt and "NO las resuelvas" in prompt
    assert IDEA_1 not in prompt and IDEA_2 not in prompt and "Respuesta modelo" not in prompt


def test_en_clase_no_se_ofrecen_nivelaciones_ni_cuestionarios(entorno):
    c, gate = entorno
    h = _auth(c)
    ruta, _ = _clase(c, h)
    chat = c.get(f"/api/v1/learning/paths/{ruta['id']}/chat", headers=h).json()

    r = _preguntar(c, h, chat["id"], "quiero aprender ecuaciones, ponme un quiz")
    envelope = next(l for l in r.text.split("\n\n") if l.startswith("event: envelope"))
    assert '"in_class": true' in envelope and '"concept_title"' in envelope
    assert "suggest_placement" not in envelope and "offer_quiz" not in envelope
    assert gate.llamadas[-1]["learning_topic"] is None and gate.llamadas[-1]["quiz_request"] is None


def test_el_paso_en_pantalla_se_puede_indicar_y_se_valida(entorno):
    c, gate = entorno
    h = _auth(c)
    ruta, _ = _clase(c, h)
    chat = c.get(f"/api/v1/learning/paths/{ruta['id']}/chat", headers=h).json()
    actual = c.get(f"/api/v1/learning/paths/{ruta['id']}", headers=h).json()["teaching"]["concept"]
    otro = next(m["concept"] for m in ruta["modules"] if m["concept"] != actual)

    assert _preguntar(c, h, chat["id"], "¿y esto?", concept=otro).status_code == 200
    sesion = gate.llamadas[-1]["learner"].class_session
    assert sesion.concept == otro and sesion.lesson_excerpt == ""  # la explicación es de otro paso

    r = _preguntar(c, h, chat["id"], "¿y esto?", concept="cocina italiana")
    assert r.status_code == 422 and r.json()["reason"] == "concept_not_in_path"


def test_un_chat_de_clase_no_admite_documentos(entorno):
    c, _ = entorno
    h = _auth(c)
    ruta, _ = _clase(c, h)
    chat = c.get(f"/api/v1/learning/paths/{ruta['id']}/chat", headers=h).json()
    r = c.put(f"/api/v1/chats/{chat['id']}", headers=h, json={"document_id": str(uuid4())})
    assert r.status_code == 422 and r.json()["reason"] == "class_chat_no_documents"


def test_borrar_la_ruta_borra_su_chat(entorno):
    c, _ = entorno
    h = _auth(c)
    ruta, _ = _clase(c, h)
    chat = c.get(f"/api/v1/learning/paths/{ruta['id']}/chat", headers=h).json()

    assert c.delete(f"/api/v1/learning/paths/{ruta['id']}", headers=h).status_code in (200, 204)
    assert c.get(f"/api/v1/chats/{chat['id']}", headers=h).status_code == 404


def test_una_duda_con_dificultad_es_senal_debil_y_un_por_que_no(entorno):
    c, _ = entorno
    h = _auth(c)
    ruta, _ = _clase(c, h)
    chat = c.get(f"/api/v1/learning/paths/{ruta['id']}/chat", headers=h).json()
    actual = c.get(f"/api/v1/learning/paths/{ruta['id']}", headers=h).json()["teaching"]["concept"]

    def concepto():
        perfil = c.get("/api/v1/learning/me/profile", headers=h).json()
        return next((x for x in perfil["mastery_by_concept"] if x["concept_key"] == actual), None)

    antes = concepto()
    _preguntar(c, h, chat["id"], "¿Por qué se hace así y no de otra forma?")
    assert concepto() == antes  # preguntar por qué es estudiar, no fallar

    _preguntar(c, h, chat["id"], "no entiendo nada de esto, estoy perdido")
    despues = concepto()
    assert despues is not None and despues != antes
    perfil = c.get("/api/v1/learning/me/profile", headers=h).json()
    assert actual not in perfil["frequent_errors"]  # pedir ayuda no es fallar (ADR-007)


@pytest.mark.asyncio
async def test_dos_peticiones_a_la_vez_no_crean_dos_chats():
    repo = InMemoryChatRepository()
    yo, ruta = uuid4(), uuid4()
    a, b = await asyncio.gather(
        repo.create_for_path(ChatAggregate.create(yo, "Clase: x", path_id=ruta)),
        repo.create_for_path(ChatAggregate.create(yo, "Clase: x", path_id=ruta)),
    )
    assert a.id == b.id and len(await repo.find_by_owner(yo)) == 1


@pytest.mark.asyncio
async def test_en_mongo_la_colision_devuelve_el_que_gano():
    from pymongo.errors import DuplicateKeyError

    from src.infrastructure.mongodb.chat_repository import MongoDBChatRepository

    yo, ruta = uuid4(), uuid4()
    ganador = ChatAggregate.create(yo, "Clase: x", path_id=ruta)

    class Coleccion:
        async def insert_one(self, doc):
            raise DuplicateKeyError("E11000 chat_por_clase")

        async def find_one(self, filtro):
            assert filtro == {"owner_id": str(yo), "path_id": str(ruta)}
            return MongoDBChatRepository._to_doc(ganador)

    class Db:
        chats = Coleccion()

    repo = MongoDBChatRepository(database=Db())
    devuelto = await repo.create_for_path(ChatAggregate.create(yo, "Clase: x", path_id=ruta))
    assert devuelto.id == ganador.id


@pytest.mark.asyncio
async def test_una_prueba_de_paso_sin_responder_tampoco_se_resuelve():
    from src.domain.aggregates.learning_path import LearningPathAggregate
    from src.domain.aggregates.quiz_aggregate import QuizAggregate
    from src.domain.value_objects.question import QuizQuestion
    from src.infrastructure.persistence.in_memory_learning_path_repo import InMemoryLearningPathRepository
    from src.infrastructure.persistence.in_memory_quiz_attempt_repo import InMemoryQuizAttemptRepository
    from src.infrastructure.persistence.in_memory_quiz_repo import InMemoryQuizRepository

    yo = uuid4()
    ruta = LearningPathAggregate.create_for_topic(yo, "python", "Python", [{"concept": "bucles", "title": "Bucles"}])
    rutas, quizzes = InMemoryLearningPathRepository(), InMemoryQuizRepository()
    await rutas.save(ruta)
    examen = QuizAggregate.create(
        None, yo, [QuizQuestion(text="¿Qué imprime este bucle?", options={"A": "1", "B": "2"}, correct_answer="B")],
        topic="python", placement_round="avanzada",
    )
    await quizzes.save(examen)
    servicio = TeachingService(
        path_repository=rutas, profile_repository=None, quiz_repository=quizzes, quiz_service=None,
        lesson_generator=None, topic_catalog=None, attempt_repository=InMemoryQuizAttemptRepository(),
    )

    sesion = await servicio.class_session(yo, ruta.id)
    assert "¿Qué imprime este bucle?" in sesion.pending_check
    assert not hasattr(sesion, "correct_answer")
