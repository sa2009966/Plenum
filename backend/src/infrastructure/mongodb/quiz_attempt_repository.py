from typing import Optional
from uuid import UUID

from motor.motor_asyncio import AsyncIOMotorDatabase

from src.domain.aggregates.quiz_attempt_aggregate import QuizAttemptAggregate
from src.domain.ports.repositories import QuizAttemptRepository
from src.infrastructure.mongodb.database import get_database


class MongoDBQuizAttemptRepository(QuizAttemptRepository):

    def __init__(self, database: Optional[AsyncIOMotorDatabase] = None) -> None:
        self._database = database

    async def _get_db(self) -> AsyncIOMotorDatabase:
        if self._database is None:
            self._database = await get_database()
        return self._database

    @staticmethod
    def _to_doc(attempt: QuizAttemptAggregate) -> dict:
        return {
            "_id": str(attempt.id),
            "quiz_id": str(attempt.quiz_id),
            "document_id": str(attempt.document_id) if attempt.document_id else None,
            "student_id": str(attempt.student_id),
            "answers": {str(k): v for k, v in attempt.answers.items()},
            "per_question_correct": list(attempt.per_question_correct),
            "per_question_score": list(attempt.per_question_score),
            "open_results": {str(k): v for k, v in attempt.open_results.items()},
            "score": attempt.score,
            "total_points": attempt.total_points,
            "completed_at": attempt.completed_at,
        }

    @staticmethod
    def _from_doc(doc: dict) -> QuizAttemptAggregate:
        return QuizAttemptAggregate(
            id=UUID(doc["_id"]),
            quiz_id=UUID(doc["quiz_id"]),
            document_id=UUID(doc["document_id"]) if doc.get("document_id") else None,
            student_id=UUID(doc["student_id"]),
            answers={int(k): v for k, v in doc.get("answers", {}).items()},
            per_question_correct=list(doc.get("per_question_correct", [])),
            # Intentos anteriores al ADR-053: sin crédito parcial ni abiertas.
            per_question_score=[float(x) for x in doc.get("per_question_score") or []],
            open_results={int(k): v for k, v in (doc.get("open_results") or {}).items()},
            score=doc.get("score", 0),
            total_points=doc.get("total_points", 0),
            completed_at=doc["completed_at"],
        )

    async def find_by_id(self, attempt_id: UUID) -> Optional[QuizAttemptAggregate]:
        db = await self._get_db()
        doc = await db.quiz_attempts.find_one({"_id": str(attempt_id)})
        return self._from_doc(doc) if doc else None

    async def find_by_quiz(self, quiz_id: UUID) -> list[QuizAttemptAggregate]:
        db = await self._get_db()
        cursor = db.quiz_attempts.find({"quiz_id": str(quiz_id)})
        return [self._from_doc(doc) async for doc in cursor]

    async def find_by_student(self, student_id: UUID) -> list[QuizAttemptAggregate]:
        db = await self._get_db()
        cursor = db.quiz_attempts.find({"student_id": str(student_id)})
        return [self._from_doc(doc) async for doc in cursor]

    async def save(self, attempt: QuizAttemptAggregate) -> None:
        db = await self._get_db()
        doc = self._to_doc(attempt)
        await db.quiz_attempts.replace_one({"_id": doc["_id"]}, doc, upsert=True)

    async def delete_by_document(self, document_id: UUID) -> int:
        db = await self._get_db()
        result = await db.quiz_attempts.delete_many({"document_id": str(document_id)})
        return int(result.deleted_count)

    async def delete_by_student(self, student_id: UUID) -> int:
        db = await self._get_db()
        result = await db.quiz_attempts.delete_many({"student_id": str(student_id)})
        return int(result.deleted_count)
