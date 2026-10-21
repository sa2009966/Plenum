from copy import deepcopy
from typing import Optional
from uuid import UUID

from src.domain.aggregates.chat import ChatAggregate
from src.domain.ports.repositories import ChatRepository


class InMemoryChatRepository(ChatRepository):

    def __init__(self) -> None:
        self._chats: dict[UUID, ChatAggregate] = {}

    async def find_by_id(self, chat_id: UUID) -> Optional[ChatAggregate]:
        return self._chats.get(chat_id)

    async def find_by_owner(self, owner_id: UUID) -> list[ChatAggregate]:
        chats = [c for c in self._chats.values() if c.owner_id == owner_id]
        chats.sort(key=lambda c: c.updated_at, reverse=True)
        # Copias independientes para que el caller pueda sumarizar sin mutar el persistido.
        return [deepcopy(c) for c in chats]

    async def save(self, chat: ChatAggregate) -> None:
        self._chats[chat.id] = chat

    async def delete(self, chat_id: UUID) -> None:
        self._chats.pop(chat_id, None)

    async def find_by_path(self, owner_id: UUID, path_id: UUID) -> Optional[ChatAggregate]:
        return next(
            (c for c in self._chats.values() if c.owner_id == owner_id and c.path_id == path_id), None
        )

    async def create_for_path(self, chat: ChatAggregate) -> ChatAggregate:
        # Sin `await` entre buscar y guardar: en un solo event loop es atómico.
        existente = next(
            (c for c in self._chats.values() if c.owner_id == chat.owner_id and c.path_id == chat.path_id),
            None,
        )
        if existente is not None:
            return existente
        self._chats[chat.id] = chat
        return chat
