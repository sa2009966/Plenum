from typing import Optional
from uuid import UUID

from motor.motor_asyncio import AsyncIOMotorDatabase

from src.domain.aggregates.chat import ChatAggregate, ChatMessage
from src.domain.ports.repositories import ChatRepository
from src.infrastructure.mongodb.database import get_database


class MongoDBChatRepository(ChatRepository):

    def __init__(self, database: Optional[AsyncIOMotorDatabase] = None) -> None:
        self._database = database

    async def _get_db(self) -> AsyncIOMotorDatabase:
        if self._database is None:
            self._database = await get_database()
        return self._database

    @staticmethod
    def _to_doc(chat: ChatAggregate) -> dict:
        return {
            "_id": str(chat.id),
            "owner_id": str(chat.owner_id),
            "title": chat.title,
            "document_id": str(chat.document_id) if chat.document_id else None,
            "path_id": str(chat.path_id) if chat.path_id else None,
            "messages": [
                {
                    "id": str(m.id),
                    "role": m.role,
                    "content": m.content,
                    "metadata": m.metadata,
                    "created_at": m.created_at,
                }
                for m in chat.messages
            ],
            "created_at": chat.created_at,
            "updated_at": chat.updated_at,
            "summary": chat.summary,
            "summary_upto": chat.summary_upto,
        }

    @staticmethod
    def _from_doc(doc: dict) -> ChatAggregate:
        messages = [
            ChatMessage(
                id=UUID(m["id"]),
                role=m["role"],
                content=m["content"],
                metadata=m.get("metadata", {}),
                created_at=m["created_at"],
            )
            for m in doc.get("messages", [])
        ]
        return ChatAggregate(
            id=UUID(doc["_id"]),
            owner_id=UUID(doc["owner_id"]),
            title=doc["title"],
            document_id=UUID(doc["document_id"]) if doc.get("document_id") else None,
            path_id=UUID(doc["path_id"]) if doc.get("path_id") else None,
            messages=messages,
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
            summary=doc.get("summary") or "",
            summary_upto=int(doc.get("summary_upto") or 0),
        )

    async def find_by_id(self, chat_id: UUID) -> Optional[ChatAggregate]:
        db = await self._get_db()
        doc = await db.chats.find_one({"_id": str(chat_id)})
        return self._from_doc(doc) if doc else None

    async def find_by_owner(self, owner_id: UUID) -> list[ChatAggregate]:
        db = await self._get_db()
        cursor = db.chats.find({"owner_id": str(owner_id)}).sort("updated_at", -1)
        results = []
        async for doc in cursor:
            results.append(self._from_doc(doc))
        return results

    async def save(self, chat: ChatAggregate) -> None:
        db = await self._get_db()
        doc = self._to_doc(chat)
        await db.chats.replace_one({"_id": doc["_id"]}, doc, upsert=True)

    async def delete(self, chat_id: UUID) -> None:
        db = await self._get_db()
        await db.chats.delete_one({"_id": str(chat_id)})

    async def find_by_path(self, owner_id: UUID, path_id: UUID) -> Optional[ChatAggregate]:
        db = await self._get_db()
        doc = await db.chats.find_one({"owner_id": str(owner_id), "path_id": str(path_id)})
        return self._from_doc(doc) if doc else None

    async def create_for_path(self, chat: ChatAggregate) -> ChatAggregate:
        """Inserta; si el índice único (owner_id, path_id) choca, devuelve el que ganó."""
        from pymongo.errors import DuplicateKeyError

        db = await self._get_db()
        try:
            await db.chats.insert_one(self._to_doc(chat))
            return chat
        except DuplicateKeyError:
            existente = await self.find_by_path(chat.owner_id, chat.path_id)
            if existente is None:  # borrado justo entre medias: se reintenta una vez
                await db.chats.insert_one(self._to_doc(chat))
                return chat
            return existente
