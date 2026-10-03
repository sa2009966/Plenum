from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.services.quiz_service import QuizService
from src.domain.ports.ia_analyst import IAAnalysisError
from src.domain.services.content_safety import UnsafeTopicError
from src.interfaces.api.dependencies import get_current_user_id, get_quiz_service
from src.interfaces.api.openapi_responses import (
    RESP_401_UNAUTHORIZED,
    RESP_404_NOT_FOUND,
    RESP_422_VALIDATION,
    RESP_429_RATE_LIMIT,
    RESP_502_BAD_GATEWAY,
)
from src.interfaces.api.quiz_mappers import quiz_to_public_response
from src.interfaces.schemas.quiz_schemas import (
    AttemptQuestionResultItem,
    DiagnosticRequest,
    PracticeRequest,
    PlacementResult,
    QuizAttemptRequest,
    QuizAttemptResponse,
    QuizPublicResponse,
)

router = APIRouter(prefix="/quizzes", tags=["Cuestionarios"])

_MSG_NO_ENCONTRADO = "Recurso no encontrado"


@router.post(
    "/diagnostic",
    response_model=QuizPublicResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Diagnóstico de entrada sobre un tema (sin material)",
    description=(
        "Lo que responde a \"quiero aprender X\": genera una escalera de ítems "
        "**fácil → media → difícil** sobre el tema y sus prerrequisitos, para medir "
        "qué sabe ya el estudiante antes de explicarle nada.\n\n"
        "No necesita documento: `document_id` viene `null` y `topic` trae el tema "
        "canónico. Se responde con `POST /quizzes/{id}/attempts` como cualquier quiz, "
        "y la evidencia cuenta **igual que la de un quiz sobre material**: son ítems "
        "calificados en el servidor, no auto-reporte.\n\n"
        "El cliente debe **ofrecerlo, no imponerlo**: un estudiante que solo quiere "
        "una respuesta rápida no tiene por qué pasar un diagnóstico para obtenerla."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_422_VALIDATION,
        **RESP_429_RATE_LIMIT,
        **RESP_502_BAD_GATEWAY,
    },
)
async def generate_diagnostic(
    body: DiagnosticRequest,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[QuizService, Depends(get_quiz_service)],
):
    try:
        quiz = await service.generate_diagnostic(body.topic, UUID(current_user_id))
    except IAAnalysisError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    except UnsafeTopicError:
        raise  # 422 con `reason` (ADR-036), en main.py
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        )
    return quiz_to_public_response(quiz)


@router.post(
    "/practice",
    response_model=QuizPublicResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Cuestionario de práctica sobre un tema (sin material)",
    description=(
        "Lo que responde a \"ponme un quiz de X\" en un chat sin documento. "
        "`num_questions` de 1 a 20 (5 por defecto). La dificultad se ajusta al nivel "
        "que el estudiante ya tenga en el tema.\n\n"
        "Se responde con `POST /quizzes/{id}/attempts` y la evidencia cuenta como la "
        "de cualquier quiz, pero **no cambia el nivel guardado**: practicar no es "
        "nivelarse (para eso está `/quizzes/diagnostic`). El intento no trae "
        "`placement`."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_422_VALIDATION,
        **RESP_429_RATE_LIMIT,
        **RESP_502_BAD_GATEWAY,
    },
)
async def generate_practice(
    body: PracticeRequest,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[QuizService, Depends(get_quiz_service)],
):
    try:
        quiz = await service.generate_practice(
            body.topic, UUID(current_user_id), body.num_questions
        )
    except IAAnalysisError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    except UnsafeTopicError:
        raise  # 422 con `reason` (ADR-036), en main.py
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        )
    return quiz_to_public_response(quiz)


@router.get(
    "/{quiz_id}",
    response_model=QuizPublicResponse,
    summary="Obtener quiz propio (sin respuestas correctas)",
    description="Devuelve el cuestionario para reintento. No incluye `correct_answer`.",
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_404_NOT_FOUND,
        **RESP_429_RATE_LIMIT,
    },
)
async def get_quiz(
    quiz_id: UUID,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[QuizService, Depends(get_quiz_service)],
):
    try:
        quiz = await service.get_quiz(quiz_id, UUID(current_user_id))
    except (ValueError, PermissionError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_MSG_NO_ENCONTRADO)
    return quiz_to_public_response(quiz)


@router.post(
    "/{quiz_id}/attempts",
    response_model=QuizAttemptResponse,
    summary="Enviar intento de quiz",
    description=(
        "Califica en el servidor las respuestas del estudiante. "
        "Body: `{\"answers\": {\"0\": \"A\", \"1\": \"C\"}}`. "
        "La respuesta incluye corrección detallada y las respuestas correctas."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_404_NOT_FOUND,
        **RESP_422_VALIDATION,
        **RESP_429_RATE_LIMIT,
        **RESP_502_BAD_GATEWAY,
    },
)
async def submit_attempt(
    quiz_id: UUID,
    body: QuizAttemptRequest,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[QuizService, Depends(get_quiz_service)],
):
    try:
        answers = {int(k): v for k, v in body.answers.items()}
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Las claves de `answers` deben ser índices numéricos de pregunta.",
        )
    try:
        result = await service.submit_attempt(quiz_id, UUID(current_user_id), answers)
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_MSG_NO_ENCONTRADO)
    except ValueError as exc:
        detail = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND
            if "no encontrado" in detail.lower() or "Quiz no encontrado" in detail
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        raise HTTPException(
            status_code=code,
            detail=_MSG_NO_ENCONTRADO if code == status.HTTP_404_NOT_FOUND else detail,
        )
    except IAAnalysisError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return QuizAttemptResponse(
        attempt_id=str(result.attempt_id),
        quiz_id=str(result.quiz_id),
        # `str(None)` mandaría la cadena "None" al cliente.
        document_id=str(result.document_id) if result.document_id else None,
        score=result.score,
        total_points=result.total_points,
        questions=[
            AttemptQuestionResultItem(
                index=q.index,
                text=q.text,
                selected=q.selected,
                correct_answer=q.correct_answer,
                is_correct=q.is_correct,
            )
            for q in result.questions
        ],
        completed_at=result.completed_at,
        placement=(
            PlacementResult(**vars(result.placement)) if result.placement else None
        ),
    )
