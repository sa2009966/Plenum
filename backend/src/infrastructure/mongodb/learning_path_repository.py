from typing import Optional
from uuid import UUID

from motor.motor_asyncio import AsyncIOMotorDatabase

from src.domain.aggregates.learning_path import (
    CheckOutcome,
    LearningModule,
    LearningPathAggregate,
    LessonVariant,
    ModuleKind,
    TeachingPhase,
    TeachingState,
)
from src.domain.ports.repositories import LearningPathRepository
from src.domain.value_objects.question import Difficulty
from src.infrastructure.mongodb.database import get_database


class MongoDBLearningPathRepository(LearningPathRepository):

    def __init__(self, database: Optional[AsyncIOMotorDatabase] = None) -> None:
        self._database = database

    async def _get_db(self) -> AsyncIOMotorDatabase:
        if self._database is None:
            self._database = await get_database()
        return self._database

    @staticmethod
    def _module_to_doc(m: LearningModule) -> dict:
        return {
            "id": str(m.id),
            "title": m.title,
            "concept": m.concept,
            "difficulty": m.difficulty.value,
            "prerequisites": list(m.prerequisites),
            "status": m.status,
            "mastery": m.mastery,
            "position": m.position,
            "kind": m.kind.value,
            "tier": m.tier,
        }

    @staticmethod
    def _module_from_doc(d: dict) -> LearningModule:
        return LearningModule(
            id=UUID(d["id"]),
            title=d.get("title", ""),
            concept=d.get("concept", ""),
            difficulty=Difficulty(d.get("difficulty", "easy")),
            prerequisites=list(d.get("prerequisites", [])),
            status=d.get("status", "locked"),
            mastery=float(d.get("mastery", 0.0)),
            position=int(d.get("position", 0)),
            kind=ModuleKind(d.get("kind", ModuleKind.CONTENT.value)),
            tier=d.get("tier", ""),
        )

    @staticmethod
    def _teaching_to_doc(t: TeachingState) -> dict:
        return {
            "phase": t.phase.value,
            "concept": t.concept,
            "return_to": t.return_to,
            "variant": t.variant.value,
            "pending_check_quiz_id": str(t.pending_check_quiz_id) if t.pending_check_quiz_id else None,
            "lesson_markdown": t.lesson_markdown,
            "last_example": t.last_example,
            "checks_on_concept": t.checks_on_concept,
            "failures_on_concept": t.failures_on_concept,
            "understood_streak": t.understood_streak,
            "last_outcome": t.last_outcome.value if t.last_outcome else None,
            "passed_concepts": list(t.passed_concepts),
            "reason": t.reason,
            "updated_at": t.updated_at,
        }

    @staticmethod
    def _teaching_from_doc(d: dict) -> TeachingState:
        if not d:
            return TeachingState()
        pendiente = d.get("pending_check_quiz_id")
        resultado = d.get("last_outcome")
        estado = TeachingState(
            phase=TeachingPhase(d.get("phase", TeachingPhase.ASSESSMENT.value)),
            concept=d.get("concept"),
            return_to=d.get("return_to"),
            variant=LessonVariant(d.get("variant", LessonVariant.INTRODUCE.value)),
            pending_check_quiz_id=UUID(pendiente) if pendiente else None,
            lesson_markdown=d.get("lesson_markdown", ""),
            last_example=d.get("last_example", ""),
            checks_on_concept=int(d.get("checks_on_concept", 0)),
            failures_on_concept=int(d.get("failures_on_concept", 0)),
            understood_streak=int(d.get("understood_streak", 0)),
            last_outcome=CheckOutcome(resultado) if resultado else None,
            passed_concepts=list(d.get("passed_concepts") or []),
            reason=d.get("reason", ""),
        )
        if d.get("updated_at"):
            estado.updated_at = d["updated_at"]
        return estado

    @staticmethod
    def _to_doc(path: LearningPathAggregate) -> dict:
        return {
            "_id": str(path.id),
            "owner_id": str(path.owner_id),
            "subject": path.subject,
            "title": path.title,
            "modules": [MongoDBLearningPathRepository._module_to_doc(m) for m in path.modules],
            "created_at": path.created_at,
            "updated_at": path.updated_at,
            "topic": path.topic,
            "next_topics": list(path.next_topics),
            "tiers": list(path.tiers),
            "teaching": MongoDBLearningPathRepository._teaching_to_doc(path.teaching),
        }

    @staticmethod
    def _from_doc(doc: dict) -> LearningPathAggregate:
        return LearningPathAggregate(
            id=UUID(doc["_id"]),
            owner_id=UUID(doc["owner_id"]),
            subject=doc.get("subject", ""),
            title=doc.get("title", "Ruta de aprendizaje"),
            modules=[MongoDBLearningPathRepository._module_from_doc(m) for m in doc.get("modules", [])],
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
            topic=doc.get("topic", ""),
            next_topics=list(doc.get("next_topics") or []),
            tiers=list(doc.get("tiers") or []),
            teaching=MongoDBLearningPathRepository._teaching_from_doc(doc.get("teaching") or {}),
        )

    async def find_by_id(self, path_id: UUID) -> Optional[LearningPathAggregate]:
        db = await self._get_db()
        doc = await db.learning_paths.find_one({"_id": str(path_id)})
        return self._from_doc(doc) if doc else None

    async def find_by_owner(self, owner_id: UUID) -> list[LearningPathAggregate]:
        db = await self._get_db()
        cursor = db.learning_paths.find({"owner_id": str(owner_id)}).sort("updated_at", -1)
        results = []
        async for doc in cursor:
            results.append(self._from_doc(doc))
        return results

    async def save(self, path: LearningPathAggregate) -> None:
        db = await self._get_db()
        doc = self._to_doc(path)
        await db.learning_paths.replace_one({"_id": doc["_id"]}, doc, upsert=True)

    async def delete(self, path_id: UUID) -> None:
        db = await self._get_db()
        await db.learning_paths.delete_one({"_id": str(path_id)})
