from typing import Optional
from uuid import UUID
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from src.domain.aggregates.student_profile import (
    ConceptMastery,
    DocumentMastery,
    PedagogicalMemory,
    StudentProfile,
)
from src.domain.exceptions import ConcurrencyError
from src.domain.memory_model import ReviewEntry
from src.domain.services.adaptive_policy import Signal, SignalKind
from src.domain.ports.repositories import StudentProfileRepository
from src.infrastructure.mongodb.database import get_database




def _aware(dt: datetime | None) -> datetime | None:
    """Mongo devuelve fechas sin zona; todas son UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)

class MongoDBStudentProfileRepository(StudentProfileRepository):

    def __init__(self, database: Optional[AsyncIOMotorDatabase] = None) -> None:
        self._database = database

    async def _get_db(self) -> AsyncIOMotorDatabase:
        if self._database is None:
            self._database = await get_database()
        return self._database

    @staticmethod
    def _to_doc(profile: StudentProfile, version: int) -> dict:
        mem = profile.pedagogical_memory
        return {
            "_id": str(profile.student_id),
            "student_id": str(profile.student_id),
            "mastery_by_document": {
                str(doc_id): {
                    "document_id": str(m.document_id),
                    "attempts": m.attempts,
                    "mastery": m.mastery,
                    "last_score_ratio": m.last_score_ratio,
                    "incorrect_streak": m.incorrect_streak,
                    "struggle_signals": m.struggle_signals,
                }
                for doc_id, m in profile.mastery_by_document.items()
            },
            "mastery_by_concept": {
                key: {
                    "concept_key": c.concept_key,
                    "attempts": c.attempts,
                    "mastery": c.mastery,
                    "last_score_ratio": c.last_score_ratio,
                    "document_ids": [str(d) for d in c.document_ids],
                    "confidence": c.confidence,
                    "last_practiced_at": c.last_practiced_at,
                    "help_requests": c.help_requests,
                    "latency_ms_ema": c.latency_ms_ema,
                    "error_streak": c.error_streak,
                    "subject": c.subject,
                    "evidence_count": c.evidence_count,
                    "weak_evidence_count": c.weak_evidence_count,
                    "half_life_days": c.half_life_days,
                    "last_reviewed_at": c.last_reviewed_at,
                    "review_log": [
                        {"at": e.at, "score_ratio": e.score_ratio, "half_life_days": e.half_life_days}
                        for e in c.review_log
                    ],
                }
                for key, c in profile.mastery_by_concept.items()
            },
            "frequent_errors": list(profile.frequent_errors),
            "pace": profile.pace,
            "total_attempts": profile.total_attempts,
            "total_struggle_signals": profile.total_struggle_signals,
            "learning_velocity": profile.learning_velocity,
            "applied_event_ids": list(profile.applied_event_ids),
            "celebrated_concepts": list(profile.celebrated_concepts),
            "level_by_topic": dict(profile.level_by_topic),
            "topic_labels": dict(profile.topic_labels),
            "explanation_style_choice": profile.explanation_style_choice,
            "voice_choice": profile.voice_choice,
            "assessment_open": profile.assessment_open,
            "assessment_choice": profile.assessment_choice,
            "session_minutes": profile.session_minutes,
            "daily_goal_minutes": profile.daily_goal_minutes,
            "pedagogical_memory": {
                "frequent_misconceptions": list(mem.frequent_misconceptions),
                "successful_examples": list(mem.successful_examples),
                "successful_analogies": list(mem.successful_analogies),
                "preferred_explanation_style": mem.preferred_explanation_style,
                "last_effective_strategies": list(mem.last_effective_strategies),
            },
            "last_interaction_at": profile.last_interaction_at,
            "last_answer_length": profile.last_answer_length,
            "adaptive_signals": {
                key: {"value": s.value, "samples": s.samples}
                for key, s in profile.adaptive_signals.items()
            },
            "updated_at": profile.updated_at,
            "version": version,
        }

    @staticmethod
    def _from_doc(doc: dict) -> StudentProfile:
        mastery: dict[UUID, DocumentMastery] = {}
        for key, raw in (doc.get("mastery_by_document") or {}).items():
            doc_id = UUID(raw.get("document_id", key))
            mastery[doc_id] = DocumentMastery(
                document_id=doc_id,
                attempts=int(raw.get("attempts", 0)),
                mastery=float(raw.get("mastery", 0.0)),
                last_score_ratio=float(raw.get("last_score_ratio", 0.0)),
                incorrect_streak=int(raw.get("incorrect_streak", 0)),
                struggle_signals=int(raw.get("struggle_signals", 0)),
            )
        concepts: dict[str, ConceptMastery] = {}
        for key, raw in (doc.get("mastery_by_concept") or {}).items():
            last_practiced = raw.get("last_practiced_at")
            concepts[key] = ConceptMastery(
                concept_key=raw.get("concept_key", key),
                attempts=int(raw.get("attempts", 0)),
                mastery=float(raw.get("mastery", 0.0)),
                last_score_ratio=float(raw.get("last_score_ratio", 0.0)),
                document_ids=[UUID(d) for d in (raw.get("document_ids") or [])],
                confidence=float(raw.get("confidence", 0.0)),
                last_practiced_at=last_practiced,
                help_requests=int(raw.get("help_requests", 0)),
                latency_ms_ema=float(raw.get("latency_ms_ema", 0.0)),
                error_streak=int(raw.get("error_streak", 0)),
                subject=raw.get("subject"),
                evidence_count=int(raw.get("evidence_count", raw.get("attempts", 0))),
                # Perfiles escritos antes del ADR-007 no distinguen: su
                # evidencia de auto-reporte quedó contada como calificada.
                # Se asume 0 y se corrige con el uso; ver deuda conocida.
                weak_evidence_count=int(raw.get("weak_evidence_count", 0)),
                half_life_days=float(raw.get("half_life_days", 14.0)),
                # Perfiles anteriores al ADR-051 no traen historial: empiezan sin
                # repasos y la vida media que tuvieran (14 días). No se inventa.
                last_reviewed_at=_aware(raw.get("last_reviewed_at")),
                review_log=[
                    ReviewEntry(
                        at=_aware(e["at"]),
                        score_ratio=float(e.get("score_ratio", 0.0)),
                        half_life_days=float(e.get("half_life_days", 14.0)),
                    )
                    for e in (raw.get("review_log") or [])
                    if e.get("at") is not None
                ],
            )
        raw_mem = doc.get("pedagogical_memory") or {}
        memory = PedagogicalMemory(
            frequent_misconceptions=list(raw_mem.get("frequent_misconceptions") or []),
            successful_examples=list(raw_mem.get("successful_examples") or []),
            successful_analogies=list(raw_mem.get("successful_analogies") or []),
            preferred_explanation_style=raw_mem.get("preferred_explanation_style", ""),
            last_effective_strategies=list(raw_mem.get("last_effective_strategies") or []),
        )
        signals: dict[str, Signal] = {}
        for key, raw in (doc.get("adaptive_signals") or {}).items():
            try:
                kind = SignalKind(key)
            except ValueError:
                continue
            signals[key] = Signal(
                kind=kind,
                value=float(raw.get("value", 0.0)),
                samples=int(raw.get("samples", 0)),
            )
        return StudentProfile(
            student_id=UUID(doc["student_id"]),
            mastery_by_document=mastery,
            mastery_by_concept=concepts,
            frequent_errors=list(doc.get("frequent_errors") or []),
            pace=doc.get("pace", "steady"),
            total_attempts=int(doc.get("total_attempts", 0)),
            total_struggle_signals=int(doc.get("total_struggle_signals", 0)),
            pedagogical_memory=memory,
            learning_velocity=float(doc.get("learning_velocity", 0.0)),
            applied_event_ids=list(doc.get("applied_event_ids") or []),
            celebrated_concepts=list(doc.get("celebrated_concepts") or []),
            level_by_topic=dict(doc.get("level_by_topic") or {}),
            topic_labels=dict(doc.get("topic_labels") or {}),
            explanation_style_choice=doc.get("explanation_style_choice") or "",
            voice_choice=doc.get("voice_choice") or "",
            assessment_open=doc.get("assessment_open"),
            assessment_choice=doc.get("assessment_choice"),
            session_minutes=int(doc.get("session_minutes") or 0),
            daily_goal_minutes=int(doc.get("daily_goal_minutes") or 0),
            last_interaction_at=doc.get("last_interaction_at"),
            last_answer_length=int(doc.get("last_answer_length", 0)),
            adaptive_signals=signals,
            updated_at=doc["updated_at"],
            version=int(doc.get("version", 0)),
        )

    async def find_by_student(self, student_id: UUID) -> Optional[StudentProfile]:
        db = await self._get_db()
        doc = await db.student_profiles.find_one({"_id": str(student_id)})
        return self._from_doc(doc) if doc else None

    async def save(self, profile: StudentProfile) -> None:
        db = await self._get_db()
        expected = int(profile.version)
        new_version = expected + 1
        payload = self._to_doc(profile, new_version)
        _id = payload["_id"]
        if expected == 0:
            existing = await db.student_profiles.find_one({"_id": _id}, projection={"version": 1})
            if existing is None:
                await db.student_profiles.insert_one(payload)
            else:
                result = await db.student_profiles.replace_one(
                    {
                        "_id": _id,
                        "$or": [{"version": 0}, {"version": {"$exists": False}}],
                    },
                    payload,
                )
                if result.matched_count == 0:
                    raise ConcurrencyError("StudentProfile concurrent update")
        else:
            result = await db.student_profiles.replace_one(
                {"_id": _id, "version": expected},
                payload,
            )
            if result.matched_count == 0:
                raise ConcurrencyError("StudentProfile concurrent update")
        profile.version = new_version

    async def delete(self, student_id: UUID) -> None:
        db = await self._get_db()
        await db.student_profiles.delete_one({"_id": str(student_id)})
