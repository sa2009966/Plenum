"""El quiz del chat sale del backend, no del cliente (fase 2 del plan de corrección).

El frontend generaba y **calificaba** los quizzes en sus propias rutas, así que
las respuestas correctas viajaban al navegador y el intento nunca llegaba al
perfil. No fue solo comodidad: para "evaluar lo que hablamos en el chat" no
existía endpoint. Estos tests blindan el que lo cierra.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.application.dto.quiz_dto import QuizPublicDTO, QuizQuestionPublicDTO
from src.interfaces.api import dependencies as deps
from src.main import app
from tests.conftest import clear_dependency_caches


@pytest.fixture
def client():
    clear_dependency_caches()
    with TestClient(app) as c:
        yield c
    clear_dependency_caches()
    app.dependency_overrides.clear()


def _token(client) -> str:
    email = f"cq_{uuid4().hex[:8]}@example.com"
    r = client.post(
        "/api/v1/auth/register",
        json={"username": f"cq_{uuid4().hex[:6]}", "email": email, "password": "SecurePass1x"},
    )
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/auth/token", data={"username": email, "password": "SecurePass1x"})
    return r.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _documento(client, token: str) -> str:
    r = client.post(
        "/api/v1/documents/",
        headers=_auth(token),
        json={
            "filename": "algebra.txt",
            "content": "Una variable representa un valor desconocido. Una ecuación iguala expresiones.",
            "subject": "Matemática",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _chat(client, token: str, document_id: str | None = None) -> str:
    body: dict = {"title": "Dudas"}
    if document_id:
        body["document_id"] = document_id
    r = client.post("/api/v1/chats/", headers=_auth(token), json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _quiz_falso(document_id: str) -> QuizPublicDTO:
    return QuizPublicDTO(
        id=uuid4(),
        document_id=UUID(document_id),
        questions=[
            QuizQuestionPublicDTO(
                index=0,
                text="¿Qué representa una variable?",
                options={"A": "Un valor desconocido", "B": "Una suma"},
                difficulty="easy",
            )
        ],
        total_points=1,
        created_at=datetime.now(timezone.utc),
    )


def _servicio_quiz_falso(document_id: str) -> AsyncMock:
    servicio = AsyncMock()
    servicio.generate = AsyncMock(return_value=_quiz_falso(document_id))
    return servicio


class TestChatQuizAPI:

    def test_genera_el_quiz_del_material_vinculado(self, client):
        token = _token(client)
        doc_id = _documento(client, token)
        chat_id = _chat(client, token, doc_id)
        servicio = _servicio_quiz_falso(doc_id)
        app.dependency_overrides[deps.get_quiz_service] = lambda: servicio

        r = client.post(f"/api/v1/chats/{chat_id}/quiz?num_questions=1", headers=_auth(token))

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["document_id"] == doc_id
        assert len(body["questions"]) == 1
        # El quiz se genera sobre el documento del chat, sin que el cliente lo diga.
        servicio.generate.assert_awaited_once()
        assert str(servicio.generate.await_args.args[0]) == doc_id

    def test_la_respuesta_nunca_lleva_la_correcta(self, client):
        """Lo que el front rompía: `correct_answer` viajando al navegador."""
        token = _token(client)
        doc_id = _documento(client, token)
        chat_id = _chat(client, token, doc_id)
        app.dependency_overrides[deps.get_quiz_service] = lambda: _servicio_quiz_falso(doc_id)

        r = client.post(f"/api/v1/chats/{chat_id}/quiz", headers=_auth(token))

        assert "correct_answer" not in r.text
        for pregunta in r.json()["questions"]:
            assert "correct_answer" not in pregunta

    def test_sin_material_vinculado_no_se_evalua(self, client):
        token = _token(client)
        chat_id = _chat(client, token)  # chat libre, sin documento

        r = client.post(f"/api/v1/chats/{chat_id}/quiz", headers=_auth(token))

        assert r.status_code == 422
        # Texto para el estudiante: qué hacer, sin rutas de la API.
        assert "documento" in r.json()["detail"].lower() and "PUT" not in r.json()["detail"]

    def test_chat_ajeno_devuelve_404(self, client):
        token_a = _token(client)
        token_b = _token(client)
        doc_id = _documento(client, token_a)
        chat_id = _chat(client, token_a, doc_id)

        r = client.post(f"/api/v1/chats/{chat_id}/quiz", headers=_auth(token_b))

        assert r.status_code == 404

    def test_num_questions_fuera_de_rango_es_422(self, client):
        token = _token(client)
        doc_id = _documento(client, token)
        chat_id = _chat(client, token, doc_id)

        r = client.post(f"/api/v1/chats/{chat_id}/quiz?num_questions=99", headers=_auth(token))

        assert r.status_code == 422

    def test_la_mezcla_del_body_llega_al_quiz_del_chat_y_del_documento(self, client):
        """ADR-053: los quizzes de documentos también aceptan la mezcla solo para esta vez."""
        from src.domain.assessment import AssessmentMix

        token = _token(client)
        doc_id = _documento(client, token)
        chat_id = _chat(client, token, doc_id)
        servicio = _servicio_quiz_falso(doc_id)
        app.dependency_overrides[deps.get_quiz_service] = lambda: servicio
        cuerpo = {"assessment": {"open_questions": 2, "choice_questions": 2}}

        assert client.post(f"/api/v1/chats/{chat_id}/quiz", headers=_auth(token), json=cuerpo).status_code == 200
        assert servicio.generate.await_args.kwargs["assessment"] == AssessmentMix(2, 2)
        assert client.post(f"/api/v1/documents/{doc_id}/quiz", headers=_auth(token), json=cuerpo).status_code == 200
        assert servicio.generate.await_args.kwargs["assessment"] == AssessmentMix(2, 2)
        # Sin body, la preferencia guardada (None).
        client.post(f"/api/v1/chats/{chat_id}/quiz", headers=_auth(token))
        assert servicio.generate.await_args.kwargs["assessment"] is None
