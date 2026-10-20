from datetime import datetime
from typing import Annotated, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ChatCreateRequest(BaseModel):
    title: Annotated[Optional[str], Field(max_length=200)] = None
    document_id: Annotated[Optional[UUID], Field(description="Opcional: linkar a un documento existente")] = None


#: Tope de un mensaje del chat (ADR-043). Sin él, un mensaje de 1 MB iba entero a la
#: moderación y al modelo: gasto en OpenAI y respuestas lentas. 20 000 deja pegar un
#: texto o un fragmento de código largo (ADR-046); el historial ya recorta cada mensaje
#: a 1500, así que solo el turno actual va entero.
MAX_CHAT_MESSAGE_CHARS = 20_000


class ChatAddMessageRequest(BaseModel):
    #: Sin "assistant": lo que dice el tutor lo escribe el servidor. Si el cliente
    #: pudiera escribirlo, un "LARIA dijo: …" falso entraba en el historial que lee el
    #: modelo y servía para saltarse el filtro de seguridad, que mira la pregunta
    #: (ADR-043). "system" queda para notas del cliente, que no entran al historial.
    role: Literal["user", "system"]
    content: Annotated[str, Field(min_length=1, max_length=MAX_CHAT_MESSAGE_CHARS)]
    metadata: Optional[dict] = None
    #: Solo en un chat de clase (ADR-054): el paso que el alumno tiene en pantalla, si
    #: no es el actual. Clave canónica de un módulo de la ruta; si no, 422.
    concept: Annotated[Optional[str], Field(default=None, max_length=200)] = None


class TitleMessageRequest(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: Annotated[str, Field(min_length=1, max_length=2_000)]


class GenerateTitleRequest(BaseModel):
    messages: Annotated[list[TitleMessageRequest], Field(min_length=1, max_length=5)]


class TitleResponse(BaseModel):
    title: Annotated[str, Field(min_length=2, max_length=120)]


class ChatMessageResponse(BaseModel):
    id: str
    role: str
    content: str
    metadata: dict = {}
    created_at: datetime


class ChatResponse(BaseModel):
    id: str
    title: str
    document_id: Optional[str] = None
    #: La ruta de la clase de este chat (ADR-054); null en un chat normal.
    path_id: Optional[str] = None
    messages: list[ChatMessageResponse] = []
    created_at: datetime
    updated_at: datetime


class ChatSummary(BaseModel):
    id: str
    title: str
    document_id: Optional[str] = None
    path_id: Optional[str] = None
    message_count: int
    last_message_preview: str = ""
    created_at: datetime
    updated_at: datetime


class ChatListResponse(BaseModel):
    chats: list[ChatSummary]
