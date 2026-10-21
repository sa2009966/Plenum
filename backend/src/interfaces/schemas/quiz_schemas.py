from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


class AssessmentConfig(BaseModel):
    """Abiertas y de opción múltiple de una evaluación (ADR-053). Por defecto 3 + 3."""

    open_questions: Annotated[int, Field(ge=0, le=10)] = 3
    choice_questions: Annotated[int, Field(ge=0, le=10)] = 3

    @model_validator(mode="after")
    def _ni_vacia_ni_examen(self):
        if not 1 <= self.open_questions + self.choice_questions <= 12:
            raise ValueError("Una evaluación lleva entre 1 y 12 preguntas.")
        return self


class QuizQuestionPublicItem(BaseModel):
    index: int
    text: str
    options: dict[str, str]
    difficulty: str = "medium"
    #: "choice" u "open" (ADR-053). Una abierta trae `options: {}` y `max_chars`.
    kind: Literal["choice", "open"] = "choice"
    max_chars: int | None = None
    #: Fase 4 (ADR-055): "before" se muestra antes de la explicación y se envía con el resto.
    position: Literal["before", "after"] = "after"
    #: Repaso de otro concepto («Repaso: Fracciones»); null si es del paso actual.
    concept_title: str | None = None


class QuizPublicResponse(BaseModel):
    id: str
    #: `null` en un diagnóstico de entrada: no nace de material (ADR-016).
    document_id: str | None = None
    #: El tema diagnosticado: la CLAVE, sin tildes. `null` en un quiz sobre material.
    topic: str | None = None
    #: El tema para mostrar, como lo escribió el estudiante ("Electrónica").
    topic_label: str | None = None
    questions: list[QuizQuestionPublicItem]
    total_points: int
    created_at: datetime


class DiagnosticRequest(BaseModel):
    """"Quiero aprender X": el tema que el estudiante quiere que se le evalúe."""

    topic: Annotated[
        str,
        Field(
            min_length=2,
            max_length=120,
            description="Tema a diagnosticar, p. ej. 'ecuaciones lineales'",
        ),
    ]


class QuizAttemptRequest(BaseModel):
    answers: Annotated[
        dict[str, str],
        Field(
            min_length=1,
            description="Mapa índice-de-pregunta (como string) → opción elegida, p. ej. {\"0\": \"A\"}",
        ),
    ]


class KeyPointResult(BaseModel):
    text: str
    covered: bool


class AttemptQuestionResultItem(BaseModel):
    index: int
    text: str
    #: La letra, o el texto que escribió en una abierta.
    selected: str | None
    #: "" en una abierta.
    correct_answer: str
    #: En una abierta, solo si el veredicto es `correct`.
    is_correct: bool
    kind: Literal["choice", "open"] = "choice"
    #: Crédito 0..1: una abierta puede ser parcial (ADR-053).
    score: float = 0.0
    verdict: Literal["correct", "partial", "incorrect", "copied", "empty"] | None = None
    #: Siempre presente en una abierta, redactado para el estudiante.
    feedback: str | None = None
    #: Las ideas clave y la respuesta modelo solo se muestran DESPUÉS de contestar.
    key_points: list[KeyPointResult] | None = None
    model_answer: str | None = None
    concept_title: str | None = None


class PlacementResult(BaseModel):
    """Veredicto de una ronda de nivelación (ADR-017)."""

    topic: str
    topic_label: str = Field(description="El tema para mostrar, con tildes")
    round: str = Field(description="`base` o `avanzada`")
    level: str = Field(description="`basico`, `intermedio` o `avanzado`")
    passed: bool
    has_next_round: bool = Field(
        description="Si hay otra ronda que ofrecer: pedirla con el mismo tema en "
        "`POST /quizzes/diagnostic`, el backend sabe cuál toca."
    )


class QuizAttemptResponse(BaseModel):
    attempt_id: str
    quiz_id: str
    #: `null` en una ronda de nivelación, que no nace de material.
    document_id: str | None = None
    score: int
    total_points: int
    questions: list[AttemptQuestionResultItem]
    completed_at: datetime
    #: Solo en rondas de nivelación. `null` en un quiz sobre material.
    placement: PlacementResult | None = None


class QuizAttemptSummaryItem(BaseModel):
    attempt_id: str
    quiz_id: str
    #: `null` en una ronda de nivelación (ADR-017).
    document_id: str | None = None
    score: int
    total_points: int
    completed_at: datetime


class TutorInteractionSummaryItem(BaseModel):
    id: str
    #: `null` si la interacción no nace de material (ADR-016).
    document_id: str | None = None
    question: str
    answer: str
    asked_at: datetime


class LearningRecommendationItem(BaseModel):
    kind: str
    message: str
    document_id: str | None = None
    concept: str | None = None
    priority: float = 0.0
    suggested_minutes: int | None = None


class LearningHistoryResponse(BaseModel):
    attempts: list[QuizAttemptSummaryItem]
    tutor_interactions: list[TutorInteractionSummaryItem]
    recommendations: list[LearningRecommendationItem] = []


class DocumentMasteryItem(BaseModel):
    document_id: str
    attempts: int
    mastery: float
    last_score_ratio: float
    struggle_signals: int = 0


class ConceptMasteryItem(BaseModel):
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


class PedagogicalMemoryItem(BaseModel):
    frequent_misconceptions: list[str] = []
    successful_examples: list[str] = []
    successful_analogies: list[str] = []
    preferred_explanation_style: str = "simple"
    last_effective_strategies: list[str] = []


class StudentProfileResponse(BaseModel):
    student_id: str
    pace: str
    total_attempts: int
    frequent_errors: list[str]
    updated_at: datetime
    mastery_by_document: list[DocumentMasteryItem]
    mastery_by_concept: list[ConceptMasteryItem] = []
    total_struggle_signals: int = 0
    learning_velocity: float = 0.0
    pedagogical_memory: PedagogicalMemoryItem | None = None
    #: Tema canónico → `basico` | `intermedio` | `avanzado`. Vacío si nunca se
    #: niveló. Es un resumen para la ruta: si discrepa del mastery, manda el
    #: mastery (ADR-017).
    level_by_topic: dict[str, str] = {}
    #: Cómo mostrar cada clave de `level_by_topic` (mismas claves, con tildes).
    topic_labels: dict[str, str] = {}
    #: Cómo eligió el estudiante que le expliquen (ADR-022); `null` = que decida
    #: LARIA. Lo deducido está en `pedagogical_memory.preferred_explanation_style`.
    explanation_style_choice: str | None = None


class PracticeRequest(BaseModel):
    """"Ponme un quiz de X": práctica sobre un tema, sin material."""

    topic: Annotated[str, Field(min_length=2, max_length=120, description="Tema a practicar")]
    num_questions: Annotated[int, Field(ge=1, le=20)] = 5
    #: Abiertas y de opción múltiple (ADR-053). Con preguntas abiertas activas, manda
    #: sobre `num_questions` y sobre la preferencia guardada.
    assessment: AssessmentConfig | None = None


StudyMethodKey = Literal["active_recall", "feynman", "worked_examples", "elaboration", "interleaving"]
StudyPaceKey = Literal["free", "pomodoro_25_5", "pomodoro_15_3"]


class AssessmentOverride(BaseModel):
    """Body opcional de la clase, la prueba de paso y los quizzes: la mezcla solo para esta vez."""

    assessment: AssessmentConfig | None = None

    def mix(self):
        """La mezcla del dominio; None = la preferencia guardada (ADR-053)."""
        from src.domain.assessment import AssessmentMix

        if self.assessment is None:
            return None
        return AssessmentMix(self.assessment.open_questions, self.assessment.choice_questions)


ExplanationStyle = Literal["simple", "step_by_step", "analogy", "visual", "mathematical", "technical"]



class LessonOptions(AssessmentOverride):
    """Body de `/lesson`: lo elegido en «Antes de empezar», que se GUARDA en la ruta (ADR-055).

    Ausente = mantener lo de la ruta; `null` = «que decida LARIA».
    """

    study_method: StudyMethodKey | None = None
    study_pace: StudyPaceKey | None = None

    def choices(self) -> dict:
        return {k: getattr(self, k) for k in ("study_method", "study_pace") if k in self.model_fields_set}

class LearningPreferences(BaseModel):
    """Cómo quiere el estudiante que le expliquen (ADR-022) y cómo evaluarle (ADR-053).

    En un PUT, un campo que no viene no cambia: cada pantalla manda solo lo suyo.
    """

    explanation_style: ExplanationStyle | None = Field(
        default=None,
        description=(
            "simple · step_by_step · analogy · visual · mathematical · technical. "
            "`null` = que lo decida LARIA. Vale para todos los temas; lo que pida en un "
            "mensaje (\"explícamelo paso a paso\") gana en ese turno."
        ),
    )
    assessment: AssessmentConfig | None = Field(
        default=None,
        description="Mezcla de preguntas de sus evaluaciones. El GET devuelve siempre la efectiva.",
    )
    #: Solo lectura (se ignora en el PUT): si las abiertas están activas en el servidor
    #: (ADR-053). Apagadas, `assessment` se guarda pero no se usa, y el cliente no
    #: debería ofrecer un ajuste sin efecto.
    open_questions_enabled: bool = False
    #: Solo lectura: si se puede preguntar a LARIA durante la clase (ADR-054).
    class_questions_enabled: bool = False
    #: Método y ritmo por defecto de sus rutas nuevas (ADR-055); null = «que decida LARIA» / libre.
    study_method: StudyMethodKey | None = None
    study_pace: StudyPaceKey | None = None
    #: Solo lectura: si los métodos de estudio están activos.
    study_methods_enabled: bool = False
