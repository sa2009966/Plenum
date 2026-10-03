from datetime import datetime
from typing import Annotated, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from src.interfaces.schemas.quiz_schemas import AttemptQuestionResultItem, QuizPublicResponse

#: `assumed`: prerrequisito sin evidencia que se da por sabido (ADR-028).
ModuleStatus = Literal["locked", "available", "in_progress", "completed", "assumed"]


class ModuleCreateItem(BaseModel):
    title: Annotated[str, Field(max_length=200)] = ""
    concept: Annotated[str, Field(min_length=1, max_length=200)]
    difficulty: Literal["easy", "medium", "hard"] = "easy"
    prerequisites: list[str] = []


class LearningPathCreateRequest(BaseModel):
    subject: Annotated[str, Field(min_length=1, max_length=128)]
    title: Annotated[Optional[str], Field(max_length=200)] = None
    modules: list[ModuleCreateItem] = []


class LearningModuleResponse(BaseModel):
    id: str
    title: str
    concept: str
    difficulty: str = "easy"
    prerequisites: list[str] = []
    status: ModuleStatus = "locked"
    mastery: float = 0.0
    position: int = 0
    #: `content` (lo que vino a aprender) o `prerequisite` (base del tema).
    kind: Literal["content", "prerequisite"] = "content"
    #: Tramo del módulo (ADR-037): `basico` · `intermedio` · `avanzado`. null en rutas manuales.
    tier: Optional[Literal["basico", "intermedio", "avanzado"]] = None


class TeachingStateResponse(BaseModel):
    """Dónde está la clase (ADR-028). Lo decide el backend; el cliente solo lo muestra."""

    phase: Literal["assessment", "teaching", "check", "remediation", "advance", "completed"]
    concept: Optional[str] = None
    concept_title: Optional[str] = None
    #: Concepto al que se vuelve tras una remediación.
    return_to: Optional[str] = None
    return_to_title: Optional[str] = None
    variant: str
    pending_check_quiz_id: Optional[str] = None
    last_outcome: Optional[Literal["understood", "partial", "not_understood"]] = None
    passed_concepts: list[str] = []
    #: Por qué la clase está aquí, en una frase para mostrar.
    reason: str = ""


class LearningPathResponse(BaseModel):
    id: str
    subject: str
    title: str
    modules: list[LearningModuleResponse] = []
    progress: float = 0.0
    created_at: datetime
    updated_at: datetime
    #: Tema canónico (clave del nivel). Vacío en rutas creadas a mano.
    topic: str = ""
    teaching: Optional[TeachingStateResponse] = None
    #: Tramos abiertos, en orden (ADR-037). La ruta crece un tramo con cada prueba de paso.
    tiers: list[Literal["basico", "intermedio", "avanzado"]] = []
    #: El tramo que abre la próxima prueba de paso (la nivelación del tema); null si
    #: ya está en avanzado o la ruta es manual. Con `teaching.phase == "completed"`
    #: y esto no nulo, la ruta no terminó: ofrece la prueba de paso.
    next_tier: Optional[Literal["intermedio", "avanzado"]] = None


class LearningPathListResponse(BaseModel):
    paths: list[LearningPathResponse]



class PathFromTopicRequest(BaseModel):
    topic: Annotated[str, Field(min_length=2, max_length=120)]


class LessonResponse(BaseModel):
    """El paso actual de la clase: explicación + comprobación pendiente."""

    path: LearningPathResponse
    #: Explicación + ejemplo en markdown. Vacío si la ruta está completada.
    markdown: str = ""
    #: Comprobación de 2 preguntas (sin respuestas). `null` si la ruta está completada.
    check: Optional[QuizPublicResponse] = None


class CheckAnswerRequest(BaseModel):
    quiz_id: UUID
    #: Índice de pregunta → letra elegida, como en /quizzes/{id}/attempts.
    answers: dict[str, str]


class NextStepResponse(BaseModel):
    phase: str
    concept: Optional[str] = None
    concept_title: Optional[str] = None
    variant: Optional[str] = None
    reason: str = ""


class CheckAnswerResponse(BaseModel):
    outcome: Literal["understood", "partial", "not_understood"]
    score: int
    total_points: int
    questions: list[AttemptQuestionResultItem]
    next: NextStepResponse
    path: LearningPathResponse



class StudyGoals(BaseModel):
    """Duración de sesión y objetivo diario (ADR-033). `null` = sin límite / sin objetivo."""

    session_minutes: Optional[Literal[10, 20, 30, 45]] = None
    daily_goal_minutes: Optional[Literal[10, 15, 30, 45, 60]] = None


class StudyPing(BaseModel):
    #: Segundos de actividad desde el aviso anterior (se cuentan como mucho 60).
    seconds: Annotated[int, Field(ge=1, le=120)] = 60
    #: Zona horaria IANA del navegador ("Europe/Madrid"), para saber qué día es "hoy".
    timezone: Annotated[Optional[str], Field(max_length=64)] = None


class StudyDayItem(BaseModel):
    date: str
    minutes: int


class StudySummaryResponse(BaseModel):
    today_minutes: int
    daily_goal_minutes: Optional[int] = None
    session_minutes: Optional[int] = None
    goal_met_today: bool = False
    #: Días seguidos cumpliendo el objetivo (o estudiando algo, si no hay objetivo).
    streak_days: int = 0
    last_7_days: list[StudyDayItem] = []


class NextTopicItem(BaseModel):
    #: Tema para `POST /learning/paths/from-topic` o `/quizzes/diagnostic`.
    topic: str
    label: str
    kind: Literal["advance", "level_up", "related"]
    reason: str
    #: true → ofrece primero la nivelación de ese tema.
    needs_placement: bool


class NextTopicsResponse(BaseModel):
    suggestions: list[NextTopicItem] = []
