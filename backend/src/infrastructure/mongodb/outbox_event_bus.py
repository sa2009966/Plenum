"""Outbox Mongo: persiste eventos y los despacha a handlers locales.

Eventos soportados (serialize/deserialize completo):
- QuizAttemptCompletedEvent
- TutorQuestionAskedEvent

Cualquier otro DomainEvent se marca processed con last_error=unsupported_event
(documentado a propósito: no inventar proyección para eventos aún no cableados).
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from src.domain.events.domain_events import (
    DomainEvent,
    ExplanationStyleChosenEvent,
    StudyGoalsChosenEvent,
    VoiceChosenEvent,
    AssessmentChosenEvent,
    ClassQuestionAskedEvent,
    StudyMethodChosenEvent,
    QuizAttemptCompletedEvent,
    TutorQuestionAskedEvent,
)
from src.domain.ports.event_bus import EventBus
from src.domain.ports.metrics_port import MetricsPort
from src.infrastructure.mongodb.database import get_database

logger = logging.getLogger(__name__)

_SUPPORTED = frozenset(
    {
        "QuizAttemptCompletedEvent",
        "TutorQuestionAskedEvent",
        "ExplanationStyleChosenEvent",
        "VoiceChosenEvent",
        "StudyGoalsChosenEvent",
        "AssessmentChosenEvent",
        "ClassQuestionAskedEvent",
        "StudyMethodChosenEvent",
    }
)

#: Cuánto dura una reclamación antes de que otro worker pueda retomar el evento.
#: Si el proceso muere a mitad de un handler, el evento no queda atrapado para
#: siempre: se vuelve a reclamar pasado este plazo. Re-procesar es seguro porque
#: el perfil deduplica por `event_id`.
DEFAULT_LEASE_SECONDS = 60.0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _event_id_of(event: DomainEvent) -> str:
    eid = getattr(event, "event_id", None)
    return str(eid) if eid is not None else str(uuid4())


def _serialize(event: DomainEvent) -> dict[str, Any]:
    if isinstance(event, QuizAttemptCompletedEvent):
        return {
            "event_type": event.event_type,
            "event_id": str(event.event_id),
            "aggregate_id": str(event.aggregate_id),
            "timestamp": event.timestamp.isoformat(),
            "quiz_id": str(event.quiz_id),
            # None en nivelaciones y prácticas (ADR-016, ADR-020): `str(None)`
            # guardaba "None", que al leerlo reventaba `UUID("None")` fuera del
            # try del worker y el evento quedaba reintentándose para siempre.
            "document_id": str(event.document_id) if event.document_id else None,
            "student_id": str(event.student_id),
            "score": event.score,
            "total": event.total,
        }
    if isinstance(event, TutorQuestionAskedEvent):
        return {
            "event_type": event.event_type,
            "event_id": str(event.event_id),
            "aggregate_id": str(event.aggregate_id),
            "timestamp": event.timestamp.isoformat(),
            "student_id": str(event.student_id),
            "document_id": str(event.document_id),
            "question": event.question,
            "answer": event.answer,
            "signal_kind": event.signal_kind,
            "signal_strength": event.signal_strength,
            "concepts": list(event.concepts),
            "latency_ms": event.latency_ms,
            "help_level": event.help_level,
            "cognitive_style": event.cognitive_style,
            "pedagogical_mode": event.pedagogical_mode,
            # Sin estos tres campos el projector no puede escribir ni señales
            # ni evidencia positiva: producción usa outbox obligatoriamente,
            # así que omitirlos deja muertas las fases de ADR-004 y ADR-006.
            "signal_observations": [list(pair) for pair in event.signal_observations],
            "answer_length": event.answer_length,
            "focus_concepts": list(event.focus_concepts),
            # Igual que los tres de arriba: producción usa outbox, así que un
            # campo que no viaje aquí deja la feature muerta solo en prod.
            "celebrated_concept": event.celebrated_concept,
        }
    if isinstance(event, StudyGoalsChosenEvent):
        return {
            "event_type": event.event_type,
            "event_id": str(event.event_id),
            "aggregate_id": str(event.aggregate_id),
            "timestamp": event.timestamp.isoformat(),
            "student_id": str(event.student_id),
            "session_minutes": event.session_minutes,
            "daily_goal_minutes": event.daily_goal_minutes,
        }
    if isinstance(event, StudyMethodChosenEvent):
        return {
            "event_type": event.event_type,
            "event_id": str(event.event_id),
            "aggregate_id": str(event.aggregate_id),
            "timestamp": event.timestamp.isoformat(),
            "student_id": str(event.student_id),
            "study_method": event.study_method,
            "study_pace": event.study_pace,
        }
    if isinstance(event, ClassQuestionAskedEvent):
        return {
            "event_type": event.event_type,
            "event_id": str(event.event_id),
            "aggregate_id": str(event.aggregate_id),
            "timestamp": event.timestamp.isoformat(),
            "student_id": str(event.student_id),
            "concept": event.concept,
            "signal_kind": event.signal_kind,
            "signal_strength": event.signal_strength,
        }
    if isinstance(event, AssessmentChosenEvent):
        return {
            "event_type": event.event_type,
            "event_id": str(event.event_id),
            "aggregate_id": str(event.aggregate_id),
            "timestamp": event.timestamp.isoformat(),
            "student_id": str(event.student_id),
            "open_questions": event.open_questions,
            "choice_questions": event.choice_questions,
        }
    if isinstance(event, VoiceChosenEvent):
        return {
            "event_type": event.event_type,
            "event_id": str(event.event_id),
            "aggregate_id": str(event.aggregate_id),
            "timestamp": event.timestamp.isoformat(),
            "student_id": str(event.student_id),
            "voice": event.voice,
        }
    if isinstance(event, ExplanationStyleChosenEvent):
        return {
            "event_type": event.event_type,
            "event_id": str(event.event_id),
            "aggregate_id": str(event.aggregate_id),
            "timestamp": event.timestamp.isoformat(),
            "student_id": str(event.student_id),
            "style": event.style,
        }
    return {
        "event_type": getattr(event, "event_type", type(event).__name__),
        "event_id": _event_id_of(event),
        "aggregate_id": str(getattr(event, "aggregate_id", "")),
        "timestamp": getattr(event, "timestamp", _utc_now()).isoformat(),
        "payload": {},
    }


def _uuid_o_none(raw: Any) -> UUID | None:
    """Lee un id opcional. "None" es lo que escribía la versión anterior."""
    if raw in (None, "", "None"):
        return None
    return UUID(str(raw))


def _deserialize(doc: dict[str, Any]) -> DomainEvent | None:
    et = doc.get("event_type")
    payload = doc.get("payload") or doc
    event_id_raw = payload.get("event_id") or doc.get("_id")
    event_id = UUID(str(event_id_raw)) if event_id_raw else uuid4()
    if et == "QuizAttemptCompletedEvent":
        return QuizAttemptCompletedEvent(
            event_id=event_id,
            aggregate_id=UUID(payload["aggregate_id"]),
            quiz_id=UUID(payload["quiz_id"]),
            document_id=_uuid_o_none(payload.get("document_id")),
            student_id=UUID(payload["student_id"]),
            score=int(payload["score"]),
            total=int(payload["total"]),
        )
    if et == "TutorQuestionAskedEvent":
        concepts = payload.get("concepts") or ()
        if isinstance(concepts, list):
            concepts = tuple(concepts)
        return TutorQuestionAskedEvent(
            event_id=event_id,
            aggregate_id=UUID(payload["aggregate_id"]),
            student_id=UUID(payload["student_id"]),
            document_id=UUID(payload["document_id"]),
            question=str(payload.get("question", "")),
            answer=str(payload.get("answer", "")),
            signal_kind=str(payload.get("signal_kind", "none")),
            signal_strength=float(payload.get("signal_strength", 0.0)),
            concepts=tuple(concepts),
            latency_ms=(
                float(payload["latency_ms"])
                if payload.get("latency_ms") is not None
                else None
            ),
            help_level=float(payload.get("help_level", 0.0)),
            cognitive_style=payload.get("cognitive_style"),
            pedagogical_mode=payload.get("pedagogical_mode"),
            signal_observations=tuple(
                (str(kind), float(value))
                for kind, value in (payload.get("signal_observations") or ())
            ),
            answer_length=int(payload.get("answer_length", 0)),
            focus_concepts=tuple(payload.get("focus_concepts") or ()),
            celebrated_concept=payload.get("celebrated_concept"),
        )
    if et == "StudyGoalsChosenEvent":
        return StudyGoalsChosenEvent(
            event_id=event_id,
            aggregate_id=UUID(payload["aggregate_id"]),
            student_id=UUID(payload["student_id"]),
            session_minutes=payload.get("session_minutes"),
            daily_goal_minutes=payload.get("daily_goal_minutes"),
        )
    if et == "StudyMethodChosenEvent":
        return StudyMethodChosenEvent(
            event_id=event_id,
            aggregate_id=UUID(payload["aggregate_id"]),
            student_id=UUID(payload["student_id"]),
            study_method=payload.get("study_method"),
            study_pace=payload.get("study_pace"),
        )
    if et == "ClassQuestionAskedEvent":
        return ClassQuestionAskedEvent(
            event_id=event_id,
            aggregate_id=UUID(payload["aggregate_id"]),
            student_id=UUID(payload["student_id"]),
            concept=str(payload["concept"]),
            signal_kind=str(payload["signal_kind"]),
            signal_strength=float(payload.get("signal_strength", 0.5)),
        )
    if et == "AssessmentChosenEvent":
        return AssessmentChosenEvent(
            event_id=event_id,
            aggregate_id=UUID(payload["aggregate_id"]),
            student_id=UUID(payload["student_id"]),
            open_questions=int(payload["open_questions"]),
            choice_questions=int(payload["choice_questions"]),
        )
    if et == "VoiceChosenEvent":
        return VoiceChosenEvent(
            event_id=event_id,
            aggregate_id=UUID(payload["aggregate_id"]),
            student_id=UUID(payload["student_id"]),
            voice=payload.get("voice"),
        )
    if et == "ExplanationStyleChosenEvent":
        return ExplanationStyleChosenEvent(
            event_id=event_id,
            aggregate_id=UUID(payload["aggregate_id"]),
            student_id=UUID(payload["student_id"]),
            style=payload.get("style"),
        )
    return None


class MongoOutboxEventBus(EventBus):
    """Persiste eventos en outbox; process_pending invoca handlers locales."""

    def __init__(
        self,
        database: AsyncIOMotorDatabase | None = None,
        metrics: MetricsPort | None = None,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
    ) -> None:
        self._database = database
        self._metrics = metrics
        self._lease_seconds = max(1.0, float(lease_seconds))
        self._subscribers: dict[type, list[Callable[[DomainEvent], Any]]] = {}

    async def _get_db(self) -> AsyncIOMotorDatabase:
        if self._database is None:
            self._database = await get_database()
        return self._database

    async def publish(self, event: DomainEvent) -> None:
        db = await self._get_db()
        payload = _serialize(event)
        await db.event_outbox.insert_one(
            {
                "_id": _event_id_of(event),
                "event_type": payload["event_type"],
                "payload": payload,
                "created_at": _utc_now(),
                "processed_at": None,
                "claimed_at": None,
                "attempts": 0,
                "last_error": None,
            }
        )

    async def subscribe(self, event_type: type, handler: Callable[[DomainEvent], Any]) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)

    async def count_pending(self) -> int:
        db = await self._get_db()
        return int(await db.event_outbox.count_documents({"processed_at": None}))

    async def _claim_next(self, db) -> dict | None:
        """Reclama en exclusiva el evento pendiente más antiguo.

        `find_one_and_update` es atómico: dos réplicas —o dos procesos durante
        un rolling deploy— no pueden llevarse el mismo evento. Antes se leían
        los pendientes y se marcaban *después* de procesarlos, así que la
        ventana entre lectura y marca permitía proyectar dos veces la misma
        interacción.
        """
        now = _utc_now()
        caducadas = now - timedelta(seconds=self._lease_seconds)
        return await db.event_outbox.find_one_and_update(
            {
                "processed_at": None,
                "$or": [
                    {"claimed_at": None},
                    {"claimed_at": {"$exists": False}},
                    {"claimed_at": {"$lt": caducadas}},
                ],
            },
            {"$set": {"claimed_at": now}},
            sort=[("created_at", 1)],
            return_document=ReturnDocument.AFTER,
        )

    async def process_pending(self, limit: int = 20) -> int:
        db = await self._get_db()
        processed = 0
        for _ in range(max(1, int(limit))):
            row = await self._claim_next(db)
            if row is None:
                break
            event = _deserialize(row)
            if event is None:
                await db.event_outbox.update_one(
                    {"_id": row["_id"]},
                    {
                        "$set": {
                            "processed_at": _utc_now(),
                            "last_error": "unsupported_event",
                        }
                    },
                )
                if self._metrics:
                    self._metrics.incr("outbox_unsupported", reason="unsupported_event")
                et = row.get("event_type", "?")
                if et not in _SUPPORTED:
                    logger.warning("outbox_unsupported_event type=%s", et)
                continue
            handlers = self._subscribers.get(type(event), [])
            try:
                for handler in handlers:
                    result = handler(event)
                    if hasattr(result, "__await__"):
                        await result
                await db.event_outbox.update_one(
                    {"_id": row["_id"]},
                    {"$set": {"processed_at": _utc_now(), "last_error": None}},
                )
                processed += 1
                if self._metrics:
                    self._metrics.incr("outbox_processed")
            except Exception as exc:  # noqa: BLE001 — worker no tumba el proceso
                logger.exception("outbox_handler_failed id=%s", row.get("_id"))
                await db.event_outbox.update_one(
                    {"_id": row["_id"]},
                    {
                        "$inc": {"attempts": 1},
                        # La reclamación NO se suelta aquí: el reintento espera
                        # a que caduque el lease. Soltarla en el acto hacía que
                        # el mismo evento se reintentara en bucle dentro del
                        # propio lote, quemándolo entero con un solo fallo.
                        "$set": {"last_error": str(exc)[:500]},
                    },
                )
                if self._metrics:
                    self._metrics.incr("outbox_failed", reason="handler_error")
        if self._metrics:
            pending = await self.count_pending()
            self._metrics.gauge("outbox_pending", float(pending))
        return processed


async def purge_personal_events(user_id) -> int:
    """Borra del outbox los eventos de una persona (borrado de cuenta, ADR-019).

    Los eventos de tutoría llevan en el payload la pregunta del estudiante y la
    respuesta; los de registro, su id como agregado. Producción usa hoy el bus en
    memoria, pero en la base quedan eventos antiguos de cuando se usó el outbox.
    """
    db = await get_database()
    clave = str(user_id)
    resultado = await db.event_outbox.delete_many(
        {"$or": [{"payload.student_id": clave}, {"aggregate_id": clave}]}
    )
    return int(resultado.deleted_count)
