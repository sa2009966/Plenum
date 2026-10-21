"""Preferencias que el estudiante declara él mismo (ADR-022)."""
from __future__ import annotations

from uuid import UUID

from src.domain.catalog.voices import is_voice
from src.domain.assessment import DEFAULT_MIX, AssessmentMix
from src.domain.events.domain_events import (
    AssessmentChosenEvent,
    ExplanationStyleChosenEvent,
    StudyMethodChosenEvent,
    VoiceChosenEvent,
)
from src.domain.ports.event_bus import EventBus
from src.domain.ports.repositories import StudentProfileRepository
from src.domain.services.cognitive_style import CognitiveStyle


class LearningPreferencesService:
    def __init__(
        self, event_bus: EventBus, profile_repository: StudentProfileRepository | None = None
    ) -> None:
        self._bus = event_bus
        self._profiles = profile_repository

    async def explanation_style(self, student_id: UUID) -> str | None:
        if self._profiles is None:
            return None
        perfil = await self._profiles.find_by_student(student_id)
        return (perfil.explanation_style_choice or None) if perfil else None

    async def choose_explanation_style(self, student_id: UUID, style: str | None) -> str | None:
        """Publica la elección; la guarda el projector (invariante 1).

        Devuelve lo elegido y no lo releído: con el outbox el perfil se escribe
        un instante después, y releer devolvería el valor anterior.
        """
        if style is not None:
            style = CognitiveStyle(style).value  # ValueError si no es un estilo
        await self._bus.publish(
            ExplanationStyleChosenEvent(aggregate_id=student_id, student_id=student_id, style=style)
        )
        return style

    async def assessment(self, student_id: UUID) -> AssessmentMix:
        """La mezcla efectiva de abiertas y opción múltiple (ADR-053); 3 + 3 si no eligió."""
        if self._profiles is None:
            return DEFAULT_MIX
        perfil = await self._profiles.find_by_student(student_id)
        return perfil.assessment() if perfil else DEFAULT_MIX

    async def choose_assessment(self, student_id: UUID, mix: AssessmentMix) -> AssessmentMix:
        """Publica la elección; la guarda el projector. Devuelve lo elegido (ver estilo)."""
        await self._bus.publish(
            AssessmentChosenEvent(
                aggregate_id=student_id,
                student_id=student_id,
                open_questions=mix.open_questions,
                choice_questions=mix.choice_questions,
            )
        )
        return mix

    async def study(self, student_id: UUID) -> tuple[str | None, str | None]:
        """Método y ritmo por defecto de sus rutas nuevas (ADR-055)."""
        if self._profiles is None:
            return None, None
        perfil = await self._profiles.find_by_student(student_id)
        return (perfil.study_method_choice, perfil.study_pace_choice) if perfil else (None, None)

    async def choose_study(self, student_id: UUID, **cambios) -> tuple[str | None, str | None]:
        """Merge: lo ausente conserva lo guardado. Publica el resultado; lo escribe el projector."""
        from src.domain.study_methods import METHOD_KEYS, PACE_KEYS

        metodo, ritmo = await self.study(student_id)
        metodo = cambios.get("study_method", metodo)
        ritmo = cambios.get("study_pace", ritmo)
        if metodo is not None and metodo not in METHOD_KEYS:
            raise ValueError("Ese método no existe.")
        if ritmo is not None and ritmo not in PACE_KEYS:
            raise ValueError("Ese ritmo no existe.")
        await self._bus.publish(
            StudyMethodChosenEvent(aggregate_id=student_id, student_id=student_id, study_method=metodo, study_pace=ritmo)
        )
        return metodo, ritmo

    async def voice(self, student_id: UUID) -> str | None:
        if self._profiles is None:
            return None
        perfil = await self._profiles.find_by_student(student_id)
        return (perfil.voice_choice or None) if perfil else None

    async def choose_voice(self, student_id: UUID, voice: str | None) -> str | None:
        if voice is not None and not is_voice(voice):
            raise ValueError("Esa voz no existe.")
        await self._bus.publish(VoiceChosenEvent(aggregate_id=student_id, student_id=student_id, voice=voice))
        return voice
