from src.domain.aggregates.student_profile import (
    ConceptMastery,
    DocumentMastery,
    PedagogicalMemory,
    StudentProfile,
)
from typing import Optional
from uuid import UUID
from datetime import datetime

from src.domain.exceptions import ConcurrencyError
from src.domain.ports.repositories import StudentProfileRepository


def _copy_memory(src: PedagogicalMemory) -> PedagogicalMemory:
    return PedagogicalMemory(
        frequent_misconceptions=list(src.frequent_misconceptions),
        successful_examples=list(src.successful_examples),
        successful_analogies=list(src.successful_analogies),
        preferred_explanation_style=src.preferred_explanation_style,
        last_effective_strategies=list(src.last_effective_strategies),
    )


def _copy_concepts(src: dict[str, ConceptMastery]) -> dict[str, ConceptMastery]:
    return {
        k: ConceptMastery(
            concept_key=v.concept_key,
            attempts=v.attempts,
            mastery=v.mastery,
            last_score_ratio=v.last_score_ratio,
            document_ids=list(v.document_ids),
            confidence=v.confidence,
            last_practiced_at=v.last_practiced_at,
            help_requests=v.help_requests,
            latency_ms_ema=v.latency_ms_ema,
            error_streak=v.error_streak,
            subject=v.subject,
            evidence_count=v.evidence_count,
            weak_evidence_count=v.weak_evidence_count,
            half_life_days=v.half_life_days,
            last_reviewed_at=v.last_reviewed_at,
            review_log=list(v.review_log),
        )
        for k, v in src.items()
    }


def _copy_mastery(src: dict[UUID, DocumentMastery]) -> dict[UUID, DocumentMastery]:
    return {
        k: DocumentMastery(
            document_id=v.document_id,
            attempts=v.attempts,
            mastery=v.mastery,
            last_score_ratio=v.last_score_ratio,
            incorrect_streak=v.incorrect_streak,
            struggle_signals=v.struggle_signals,
        )
        for k, v in src.items()
    }


def _clone_profile(profile: StudentProfile, version: int | None = None) -> StudentProfile:
    return StudentProfile(
        student_id=profile.student_id,
        mastery_by_document=_copy_mastery(profile.mastery_by_document),
        mastery_by_concept=_copy_concepts(profile.mastery_by_concept),
        frequent_errors=list(profile.frequent_errors),
        pace=profile.pace,
        total_attempts=profile.total_attempts,
        total_struggle_signals=profile.total_struggle_signals,
        pedagogical_memory=_copy_memory(profile.pedagogical_memory),
        learning_velocity=profile.learning_velocity,
        applied_event_ids=list(profile.applied_event_ids),
        celebrated_concepts=list(profile.celebrated_concepts),
        last_interaction_at=profile.last_interaction_at,
        last_answer_length=profile.last_answer_length,
        # Signal es frozen: copiar el dict basta para aislar el agregado.
        adaptive_signals=dict(profile.adaptive_signals),
        level_by_topic=dict(profile.level_by_topic),
        topic_labels=dict(profile.topic_labels),
        explanation_style_choice=profile.explanation_style_choice,
        voice_choice=profile.voice_choice,
        session_minutes=profile.session_minutes,
        daily_goal_minutes=profile.daily_goal_minutes,
        updated_at=profile.updated_at,
        version=profile.version if version is None else version,
    )


class InMemoryStudentProfileRepository(StudentProfileRepository):

    def __init__(self) -> None:
        self._profiles: dict[UUID, StudentProfile] = {}

    async def find_by_student(self, student_id: UUID) -> Optional[StudentProfile]:
        profile = self._profiles.get(student_id)
        if profile is None:
            return None
        return _clone_profile(profile)

    async def save(self, profile: StudentProfile) -> None:
        existing = self._profiles.get(profile.student_id)
        expected = int(profile.version)
        if existing is not None and existing.version != expected:
            raise ConcurrencyError("StudentProfile concurrent update")
        if existing is None and expected != 0:
            raise ConcurrencyError("StudentProfile concurrent update")
        new_version = expected + 1
        stored = _clone_profile(profile, version=new_version)
        self._profiles[profile.student_id] = stored
        profile.version = new_version

    async def delete(self, student_id: UUID) -> None:
        self._profiles.pop(student_id, None)
