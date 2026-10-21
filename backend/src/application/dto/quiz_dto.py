from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass
class QuizQuestionPublicDTO:
    index: int
    text: str
    options: dict[str, str]
    difficulty: str
    #: "choice" u "open" (ADR-053). Una abierta no trae opciones y sí `max_chars`.
    kind: str = "choice"
    max_chars: int | None = None
    position: str = "after"
    concept_title: str | None = None


@dataclass
class QuizPublicDTO:
    id: UUID
    # Ausente en un diagnóstico de entrada, que nace de un tema (ADR-016).
    document_id: UUID | None
    questions: list[QuizQuestionPublicDTO]
    total_points: int
    created_at: datetime
    #: El tema diagnosticado. Va al final y con default para no obligar a
    #: reescribir a todo el que ya construía este DTO con material.
    topic: str | None = None
    topic_label: str | None = None


@dataclass
class AttemptQuestionResultDTO:
    index: int
    text: str
    selected: str | None
    correct_answer: str
    is_correct: bool
    # ADR-053: crédito 0..1 y, en una abierta, su corrección. Las ideas clave y la
    # respuesta modelo solo salen aquí, después de contestar.
    kind: str = "choice"
    score: float = 0.0
    verdict: str | None = None
    feedback: str | None = None
    key_points: list[tuple[str, bool]] | None = None
    model_answer: str | None = None
    #: Repaso de otro concepto (ADR-055, fase 4): no decide el paso actual.
    concept_title: str | None = None


@dataclass
class PlacementResultDTO:
    """Veredicto de una ronda de nivelación (ADR-017)."""

    topic: str
    topic_label: str
    round: str
    level: str
    passed: bool
    has_next_round: bool


@dataclass
class QuizAttemptResultDTO:
    attempt_id: UUID
    quiz_id: UUID
    document_id: UUID | None
    score: int
    total_points: int
    questions: list[AttemptQuestionResultDTO]
    completed_at: datetime
    #: Presente solo si el quiz era una ronda de nivelación.
    placement: PlacementResultDTO | None = None


@dataclass
class QuizAttemptSummaryDTO:
    attempt_id: UUID
    quiz_id: UUID
    document_id: UUID | None
    score: int
    total_points: int
    completed_at: datetime


@dataclass
class TutorInteractionSummaryDTO:
    id: UUID
    document_id: UUID | None
    question: str
    answer: str
    asked_at: datetime


@dataclass
class LearningRecommendationDTO:
    kind: str
    message: str
    document_id: UUID | None = None
    concept: str | None = None
    priority: float = 0.0
    suggested_minutes: int | None = None


@dataclass
class LearningHistoryDTO:
    attempts: list[QuizAttemptSummaryDTO] = field(default_factory=list)
    tutor_interactions: list[TutorInteractionSummaryDTO] = field(default_factory=list)
    recommendations: list[LearningRecommendationDTO] = field(default_factory=list)


@dataclass
class DocumentMasteryDTO:
    document_id: UUID
    attempts: int
    mastery: float
    last_score_ratio: float
    struggle_signals: int = 0


@dataclass
class ConceptMasteryDTO:
    concept_key: str
    attempts: int
    mastery: float
    last_score_ratio: float
    effective_mastery: float = 0.0
    confidence: float = 0.0
    last_practiced_at: datetime | None = None
    subject: str | None = None
    help_requests: int = 0
    error_streak: int = 0


@dataclass
class PedagogicalMemoryDTO:
    frequent_misconceptions: list[str] = field(default_factory=list)
    successful_examples: list[str] = field(default_factory=list)
    successful_analogies: list[str] = field(default_factory=list)
    preferred_explanation_style: str = "simple"
    last_effective_strategies: list[str] = field(default_factory=list)


@dataclass
class StudentProfileDTO:
    student_id: UUID
    pace: str
    total_attempts: int
    frequent_errors: list[str]
    updated_at: datetime
    mastery_by_document: list[DocumentMasteryDTO] = field(default_factory=list)
    mastery_by_concept: list[ConceptMasteryDTO] = field(default_factory=list)
    total_struggle_signals: int = 0
    learning_velocity: float = 0.0
    pedagogical_memory: PedagogicalMemoryDTO | None = None
    #: Veredicto de nivelación por tema (ADR-017).
    level_by_topic: dict[str, str] = field(default_factory=dict)
    topic_labels: dict[str, str] = field(default_factory=dict)
    explanation_style_choice: str | None = None
