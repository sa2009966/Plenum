from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DomainEvent:
    event_id: UUID
    aggregate_id: UUID
    timestamp: datetime
    event_type: str


@dataclass(kw_only=True)
class DomainEventBase(DomainEvent):
    aggregate_id: UUID
    event_id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=_utc_now)

    @property
    def event_type(self) -> str:
        return type(self).__name__


@dataclass(kw_only=True)
class UserRegisteredEvent(DomainEventBase):
    email: str


@dataclass(kw_only=True)
class UserDeactivatedEvent(DomainEventBase):
    pass


@dataclass(kw_only=True)
class DocumentUploadedEvent(DomainEventBase):
    owner_id: UUID
    filename: str


@dataclass(kw_only=True)
class DocumentDeletedEvent(DomainEventBase):
    owner_id: UUID


@dataclass(kw_only=True)
class AnalysisCompletedEvent(DomainEventBase):
    document_id: UUID
    summary_length: int


@dataclass(kw_only=True)
class AnalysisFailedEvent(DomainEventBase):
    document_id: UUID
    error_message: str


@dataclass(kw_only=True)
class QuizGeneratedEvent(DomainEventBase):
    document_id: UUID
    owner_id: UUID
    num_questions: int


@dataclass(kw_only=True)
class QuizAttemptCompletedEvent(DomainEventBase):
    quiz_id: UUID
    # None en un diagnóstico de entrada: la evidencia va a los conceptos y no
    # hay documento cuyo mastery mover (ADR-016).
    document_id: UUID | None
    student_id: UUID
    score: int
    total: int


@dataclass(kw_only=True)
class TutorQuestionAskedEvent(DomainEventBase):
    student_id: UUID
    document_id: UUID
    question: str
    answer: str
    signal_kind: str = "none"
    signal_strength: float = 0.0
    concepts: tuple[str, ...] = ()
    latency_ms: float | None = None
    help_level: float = 0.0
    cognitive_style: str | None = None
    pedagogical_mode: str | None = None
    # Observaciones de señal medidas en el borde con wall-clock real. El
    # projector las aplica pero no las calcula: no podría reconstruir el gap
    # vivido por el estudiante (ADR-004, Decisión 2).
    signal_observations: tuple[tuple[str, float], ...] = ()
    answer_length: int = 0
    # Conceptos sobre los que versó el turno: son los que reciben evidencia
    # positiva si el estudiante se autocorrige (ADR-006, fase 2).
    focus_concepts: tuple[str, ...] = ()
    # Hito reconocido al estudiante en este turno. Viaja en el evento porque el
    # perfil tiene un único escritor —el projector— y la marca debe quedar
    # dentro de la misma idempotencia por `event_id` (ADR-009).
    celebrated_concept: str | None = None


@dataclass(kw_only=True)
class ExplanationStyleChosenEvent(DomainEventBase):
    """El estudiante eligió cómo quiere que le expliquen (ADR-022).

    Viaja como evento aunque no sea evidencia: el perfil tiene un único escritor
    —el projector— y una preferencia no es excepción a eso (invariante 1).
    `style` None = "que lo decida LARIA".
    """

    student_id: UUID
    style: str | None = None


@dataclass(kw_only=True)
class VoiceChosenEvent(DomainEventBase):
    """El estudiante eligió la voz del tutor (ADR-030). `voice` None = la de por defecto."""

    student_id: UUID
    voice: str | None = None


@dataclass(kw_only=True)
class ClassQuestionAskedEvent(DomainEventBase):
    """Una duda en clase que muestra dificultad (ADR-054). Señal débil, nunca nota."""

    student_id: UUID
    concept: str
    signal_kind: str
    signal_strength: float = 0.5


@dataclass(kw_only=True)
class AssessmentChosenEvent(DomainEventBase):
    """Cuántas abiertas y de opción múltiple quiere en sus evaluaciones (ADR-053)."""

    student_id: UUID
    open_questions: int
    choice_questions: int


@dataclass(kw_only=True)
class StudyGoalsChosenEvent(DomainEventBase):
    """Duración de sesión y objetivo diario (ADR-033). None = sin límite / sin objetivo."""

    student_id: UUID
    session_minutes: int | None = None
    daily_goal_minutes: int | None = None
