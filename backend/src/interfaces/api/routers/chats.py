from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
import json
import logging

from src.application.services.conversation_memory import ConversationMemory
from src.application.services.chat_tutor_service import ChatTutorService
from src.application.services.quiz_service import QuizService
from src.domain.aggregates.chat import ChatAggregate
from src.domain.ports.chat_title_generator import ChatTitleGenerator, TitleMessage
from src.domain.ports.ia_analyst import IAAnalysisError
from src.domain.ports.repositories import ChatRepository
from src.interfaces.api.errors import ReasonedError
from src.interfaces.api.dependencies import (
    get_chat_repo,
    get_chat_title_generator,
    get_conversation_memory,
    get_chat_tutor_service,
    get_current_user_id,
    get_quiz_service,
    get_teaching_service,
)
from src.interfaces.api.openapi_responses import (
    RESP_401_UNAUTHORIZED,
    RESP_404_NOT_FOUND,
    RESP_422_VALIDATION,
    RESP_429_RATE_LIMIT,
    RESP_502_BAD_GATEWAY,
)
from src.domain.services.response_envelope import plain_envelope
from src.interfaces.api.quiz_mappers import quiz_to_public_response
from src.interfaces.schemas.quiz_schemas import AssessmentOverride, QuizPublicResponse
from src.interfaces.schemas.chat_schemas import (
    ChatAddMessageRequest,
    ChatCreateRequest,
    ChatListResponse,
    ChatMessageResponse,
    ChatResponse,
    ChatSummary,
    GenerateTitleRequest,
    TitleResponse,
)

logger = logging.getLogger("laria.chat")

router = APIRouter(prefix="/chats", tags=["Chats"])

_MSG_NO_ENCONTRADO = "Recurso no encontrado"


def _map_chat(chat: ChatAggregate) -> ChatResponse:
    return ChatResponse(
        id=str(chat.id),
        title=chat.title,
        document_id=str(chat.document_id) if chat.document_id else None,
        path_id=str(chat.path_id) if chat.path_id else None,
        messages=[
            ChatMessageResponse(
                id=str(m.id),
                role=m.role,
                content=m.content,
                metadata=m.metadata,
                created_at=m.created_at,
            )
            for m in chat.messages
        ],
        created_at=chat.created_at,
        updated_at=chat.updated_at,
    )


def _map_summary(chat: ChatAggregate) -> ChatSummary:
    last_preview = ""
    if chat.messages:
        last_preview = chat.messages[-1].content[:80]
    return ChatSummary(
        id=str(chat.id),
        title=chat.title,
        document_id=str(chat.document_id) if chat.document_id else None,
        path_id=str(chat.path_id) if chat.path_id else None,
        message_count=len(chat.messages),
        last_message_preview=last_preview,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
    )


@router.get("/", response_model=ChatListResponse, summary="Listar mis chats")
async def list_chats(
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    repo: Annotated[ChatRepository, Depends(get_chat_repo)],
):
    chats = await repo.find_by_owner(UUID(current_user_id))
    return ChatListResponse(chats=[_map_summary(c) for c in chats])


@router.post("/", response_model=ChatResponse, status_code=201, summary="Crear nuevo chat")
async def create_chat(
    body: ChatCreateRequest,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    repo: Annotated[ChatRepository, Depends(get_chat_repo)],
):
    chat = ChatAggregate.create(
        owner_id=UUID(current_user_id),
        title=body.title,
        document_id=body.document_id,
    )
    await repo.save(chat)
    return _map_chat(chat)


@router.post(
    "/generate-title",
    response_model=TitleResponse,
    summary="Generar título inicial del chat",
    description=(
        "Genera un título breve a partir de hasta cinco mensajes. "
        "No modifica ningún chat; el cliente decide si persiste el título generado."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_422_VALIDATION,
        **RESP_429_RATE_LIMIT,
        **RESP_502_BAD_GATEWAY,
    },
)
async def generate_title(
    body: GenerateTitleRequest,
    _current_user_id: Annotated[str, Depends(get_current_user_id)],
    generator: Annotated[ChatTitleGenerator, Depends(get_chat_title_generator)],
):
    try:
        title = await generator.generate_chat_title(
            [TitleMessage(role=message.role, content=message.content) for message in body.messages]
        )
    except IAAnalysisError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return TitleResponse(title=title)


@router.get("/{chat_id}", response_model=ChatResponse, summary="Obtener chat por id")
async def get_chat(
    chat_id: UUID,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    repo: Annotated[ChatRepository, Depends(get_chat_repo)],
):
    chat = await repo.find_by_id(chat_id)
    if chat is None or str(chat.owner_id) != current_user_id:
        raise HTTPException(status_code=404, detail=_MSG_NO_ENCONTRADO)
    return _map_chat(chat)


@router.put("/{chat_id}", response_model=ChatResponse, summary="Actualizar chat")
async def update_chat(
    chat_id: UUID,
    body: ChatCreateRequest,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    repo: Annotated[ChatRepository, Depends(get_chat_repo)],
):
    chat = await repo.find_by_id(chat_id)
    if chat is None or str(chat.owner_id) != current_user_id:
        raise HTTPException(status_code=404, detail=_MSG_NO_ENCONTRADO)
    if body.title is not None:
        try:
            chat.set_title(body.title)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    if body.document_id is not None:
        if chat.path_id is not None:
            # El contexto de un chat de clase es la clase; un documento lo cambiaría (ADR-054).
            raise ReasonedError(422, "Un chat de clase no admite documentos.", "class_chat_no_documents")
        chat.link_document(body.document_id)
    await repo.save(chat)
    return _map_chat(chat)


async def _sesion_de_clase(chat: ChatAggregate, usuario: UUID, concept: str | None, teaching):
    """El contexto de la clase de un chat vinculado a una ruta (ADR-054), o None.

    Con el interruptor apagado, o si la ruta ya no existe, el chat responde como
    uno normal. Un `concept` que no es de la ruta es un error del cliente: 422.
    """
    from src.application.services.teaching_service import ConceptNotInPath, PathNotFound
    from src.infrastructure.config import settings

    if chat.path_id is None or not settings.CLASS_QUESTIONS_ENABLED:
        return None
    try:
        return await teaching.class_session(usuario, chat.path_id, concept)
    except PathNotFound:
        return None
    except ConceptNotInPath:
        raise ReasonedError(422, "Ese paso no es de esta clase.", "concept_not_in_path")


@router.post("/{chat_id}/messages", response_model=ChatResponse, summary="Agregar mensaje")
async def add_message(
    chat_id: UUID,
    body: ChatAddMessageRequest,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    repo: Annotated[ChatRepository, Depends(get_chat_repo)],
    tutor: Annotated[ChatTutorService, Depends(get_chat_tutor_service)],
    memory: Annotated[ConversationMemory, Depends(get_conversation_memory)],
    teaching=Depends(get_teaching_service),
):
    chat = await repo.find_by_id(chat_id)
    if chat is None or str(chat.owner_id) != current_user_id:
        raise HTTPException(status_code=404, detail=_MSG_NO_ENCONTRADO)
    sesion = await _sesion_de_clase(chat, UUID(current_user_id), body.concept, teaching) if body.role == "user" else None
    # Antes de añadir el mensaje actual: el historial es lo que se dijo ANTES.
    # Solo un turno la necesita: una nota `system` no gasta un resumen.
    historial = await memory.recall(chat) if body.role == "user" else ()
    try:
        chat.add_message(role=body.role, content=body.content, metadata=body.metadata)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if body.role == "user":
        try:
            response = await tutor.answer(
                document_id=chat.document_id,
                question=body.content,
                student_id=UUID(current_user_id),
                history=historial,
                # Solo en un chat de clase: el de siempre llama al tutor igual que antes.
                **({"class_session": sesion} if sesion is not None else {}),
            )
            chat.add_message(
                role="assistant",
                content=response.content,
                metadata=response.envelope.to_dict(),
            )
        except Exception:
            fallo = plain_envelope(
                "error",
                "Lo siento, no pude generar una respuesta en este momento. Intenta de nuevo.",
                grounded=chat.document_id is not None,
            )
            chat.add_message(
                role="system",
                content=fallo.payload["content"],
                metadata=fallo.to_dict(),
            )

    await repo.save(chat)
    return _map_chat(chat)


@router.post(
    "/{chat_id}/stream",
    summary="Respuesta del tutor en streaming (SSE)",
    description=(
        "Server-Sent Events: thinking → token(s) → envelope → done. "
        "El mensaje del usuario y la respuesta final se persisten en el chat."
    ),
)
async def stream_message(
    chat_id: UUID,
    body: ChatAddMessageRequest,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    repo: Annotated[ChatRepository, Depends(get_chat_repo)],
    tutor: Annotated[ChatTutorService, Depends(get_chat_tutor_service)],
    memory: Annotated[ConversationMemory, Depends(get_conversation_memory)],
    teaching=Depends(get_teaching_service),
):
    if body.role != "user":
        raise HTTPException(status_code=422, detail="El streaming solo acepta mensajes 'user'")

    chat = await repo.find_by_id(chat_id)
    if chat is None or str(chat.owner_id) != current_user_id:
        raise HTTPException(status_code=404, detail=_MSG_NO_ENCONTRADO)
    # Antes de abrir el stream: un concepto inválido tiene que poder ser un 422.
    sesion = await _sesion_de_clase(chat, UUID(current_user_id), body.concept, teaching)
    historial = await memory.recall(chat)
    try:
        chat.add_message(role="user", content=body.content, metadata=body.metadata)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await repo.save(chat)

    question = body.content

    async def event_stream():
        def _sse(event: str, data: dict) -> str:
            return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        try:
            yield _sse("thinking", {})
            pieces: list[str] = []
            envelope = None
            final = ""
            async for token, env in tutor.answer_stream(
                document_id=chat.document_id,
                question=question,
                student_id=UUID(current_user_id),
                history=historial,
                **({"class_session": sesion} if sesion is not None else {}),
            ):
                if env is not None:
                    envelope = env
                    final = token
                else:
                    pieces.append(token)
                    yield _sse("token", {"content": token})

            # Se guarda el texto con el que cerró el servicio, no los tokens crudos: ahí
            # ya se quitaron los esquemas que no se pueden pintar (ADR-048).
            answer = final if envelope is not None else "".join(pieces)
            metadata = (
                envelope.to_dict()
                if envelope
                else plain_envelope(
                    "answer", answer, grounded=chat.document_id is not None
                ).to_dict()
            )
            chat.add_message(role="assistant", content=answer, metadata=metadata)
            await repo.save(chat)

            if envelope is not None:
                yield _sse("envelope", envelope.to_dict())
            yield _sse("done", {"message_id": str(chat.messages[-1].id)})
        except Exception as exc:
            # Antes no quedaba rastro: el estudiante veía el error y en Render no
            # había forma de saber si fue el proveedor, un timeout o un fallo nuestro.
            logger.exception("chat_stream_fallo chat=%s %s", chat_id, type(exc).__name__)
            yield _sse(
                "error",
                plain_envelope(
                    "error",
                    # Los mensajes del proveedor ya están escritos para el estudiante
                    # (p. ej. «espera unos segundos»); lo demás no se le enseña.
                    str(exc) if isinstance(exc, IAAnalysisError) else "No pude generar la respuesta. Intenta de nuevo.",
                    grounded=chat.document_id is not None,
                ).to_dict(),
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/{chat_id}/quiz",
    response_model=QuizPublicResponse,
    summary="Generar cuestionario sobre el material del chat",
    description=(
        "Genera y persiste un cuestionario a partir del **documento vinculado al chat**. "
        "La respuesta NO incluye las respuestas correctas: se califican en servidor al enviar "
        "el intento a `POST /quizzes/{quiz_id}/attempts`, que es lo que convierte el intento en "
        "evidencia del perfil. Sin material vinculado responde **422**: evaluar sin material "
        "sería preguntar por algo que el sistema no puede corregir contra nada."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_404_NOT_FOUND,
        **RESP_422_VALIDATION,
        **RESP_429_RATE_LIMIT,
        **RESP_502_BAD_GATEWAY,
    },
)
async def generate_chat_quiz(
    chat_id: UUID,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    repo: Annotated[ChatRepository, Depends(get_chat_repo)],
    service: Annotated[QuizService, Depends(get_quiz_service)],
    num_questions: int = Query(5, ge=1, le=20, description="Cantidad de preguntas (1-20). Con las abiertas activas manda la mezcla."),
    body: Optional[AssessmentOverride] = None,
):
    chat = await repo.find_by_id(chat_id)
    if chat is None or str(chat.owner_id) != current_user_id:
        raise HTTPException(status_code=404, detail=_MSG_NO_ENCONTRADO)
    if chat.document_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                # Lo lee el estudiante (el cliente muestra el detail): sin rutas de la
                # API. Antes decía "Vincula un documento (PUT /chats/{chat_id})".
                "Este chat no tiene un documento. Sube uno o adjúntalo al chat "
                "para hacer un quiz sobre él."
            ),
        )
    try:
        quiz = await service.generate(
            chat.document_id, UUID(current_user_id), num_questions=num_questions,
            assessment=body.mix() if body else None,
        )
    except (ValueError, PermissionError):
        raise HTTPException(status_code=404, detail=_MSG_NO_ENCONTRADO)
    except IAAnalysisError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return quiz_to_public_response(quiz)


@router.delete("/{chat_id}", status_code=204, summary="Eliminar chat")
async def delete_chat(
    chat_id: UUID,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    repo: Annotated[ChatRepository, Depends(get_chat_repo)],
):
    chat = await repo.find_by_id(chat_id)
    if chat is None or str(chat.owner_id) != current_user_id:
        raise HTTPException(status_code=404, detail=_MSG_NO_ENCONTRADO)
    await repo.delete(chat_id)
