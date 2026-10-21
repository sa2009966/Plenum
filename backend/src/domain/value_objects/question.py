from dataclasses import dataclass, field
from enum import Enum


class Difficulty(Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class BloomLevel(Enum):
    REMEMBER = "remember"
    UNDERSTAND = "understand"
    APPLY = "apply"
    ANALYZE = "analyze"
    EVALUATE = "evaluate"
    CREATE = "create"


@dataclass(frozen=True)
class Question:
    text: str
    difficulty: Difficulty = Difficulty.EASY
    bloom_level: BloomLevel = BloomLevel.REMEMBER

    def __post_init__(self):
        if not self.text or len(self.text.strip()) == 0:
            raise ValueError("Question text cannot be empty")
        if len(self.text) > 4000:
            raise ValueError("Question text cannot exceed 4000 characters")


#: Tipos de pregunta (ADR-053). "choice" es el de siempre; "open" se redacta y la
#: corrige el corrector de respuestas abiertas (ADR-052).
CHOICE = "choice"
OPEN = "open"


@dataclass(frozen=True)
class QuizQuestion:
    text: str
    options: dict[str, str]  # {"A": "option", "B": "option", ...}; vacío en una abierta
    correct_answer: str  # la letra; "" en una abierta
    difficulty: Difficulty = Difficulty.MEDIUM
    concept_tags: tuple[str, ...] = ()
    kind: str = CHOICE
    #: Solo en una abierta: lo que la respuesta tiene que expresar (1 a 5 ideas) y
    #: una respuesta de ejemplo. Nunca se envían al cliente antes de contestar.
    key_points: tuple[str, ...] = ()
    model_answer: str = ""
    #: Fase 4 (ADR-055): "before" = se muestra antes de la explicación (recuerdo activo).
    position: str = "after"
    #: Título de OTRO concepto cuando la pregunta es un repaso («Repaso: Fracciones»).
    concept_title: str = ""

    @property
    def is_review(self) -> bool:
        """Repasa otro concepto: cuenta como evidencia de ese, no decide el paso actual."""
        return bool(self.concept_title)

    @property
    def is_open(self) -> bool:
        return self.kind == OPEN

    def as_open_question(self):
        from src.domain.open_answers import OpenQuestion

        return OpenQuestion(text=self.text, key_points=self.key_points, model_answer=self.model_answer)

    def __post_init__(self):
        if not self.text or len(self.text.strip()) == 0:
            raise ValueError("Question text cannot be empty")
        object.__setattr__(
            self,
            "concept_tags",
            tuple(t.strip().lower() for t in self.concept_tags if t and str(t).strip()),
        )
        if self.kind not in (CHOICE, OPEN):
            raise ValueError(f"Tipo de pregunta desconocido: {self.kind}")
        if self.kind == OPEN:
            if self.options or self.correct_answer:
                raise ValueError("Una pregunta abierta no lleva opciones ni letra correcta")
            object.__setattr__(self, "key_points", tuple(str(k).strip() for k in self.key_points if str(k).strip()))
            object.__setattr__(self, "model_answer", (self.model_answer or "").strip())
            self.as_open_question()  # valida la rúbrica (1 a 5 ideas clave)
            return
        if len(self.options) < 2:
            raise ValueError("Quiz question must have at least 2 options")
        if self.correct_answer not in self.options:
            raise ValueError(f"Correct answer '{self.correct_answer}' not in options")
        for key in self.options:
            if len(key) != 1:
                raise ValueError(f"Option keys must be single characters: {key}")


@dataclass(frozen=True)
class Quiz:
    questions: list[QuizQuestion] = field(default_factory=list)

    @property
    def total_points(self) -> int:
        return len(self.questions) * 10

    @property
    def total_questions(self) -> int:
        return len(self.questions)
