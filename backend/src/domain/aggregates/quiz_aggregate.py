from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4

from src.domain.events.domain_events import DomainEvent, QuizGeneratedEvent
from src.domain.value_objects.question import Difficulty, QuizQuestion


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_difficulty(value) -> Difficulty:
    if isinstance(value, Difficulty):
        return value
    return Difficulty(str(value).lower())


@dataclass(frozen=True)
class QuizGrade:
    """Resultado de calificar un intento: evidencia de aprendizaje por pregunta."""

    per_question_correct: tuple[bool, ...]
    score: int
    total_points: int
    #: Crédito por pregunta, 0..1: una abierta puede ser parcial (ADR-053). Vacío
    #: en intentos anteriores: entonces vale lo mismo que `per_question_correct`.
    per_question_score: tuple[float, ...] = ()
    #: Índice → corrección de la abierta (veredicto, nota, ideas cubiertas, feedback).
    open_grades: dict = field(default_factory=dict)

    def score_at(self, i: int) -> float:
        if i < len(self.per_question_score):
            return self.per_question_score[i]
        return 1.0 if self.per_question_correct[i] else 0.0

    @property
    def correct_count(self) -> int:
        return sum(1 for c in self.per_question_correct if c)


@dataclass
class QuizAggregate:
    id: UUID = field(default_factory=uuid4)
    # Opcional desde el ADR-016: un diagnóstico de entrada nace de un TEMA, no
    # de material subido. Quien lo consuma debe tratarlo como ausente de verdad,
    # no sustituirlo por un id inventado.
    document_id: UUID | None = None
    topic: str | None = None
    #: Ronda de nivelación que representa este quiz, si lo es (ADR-017).
    #: Sin esto el projector no puede distinguir un intento de nivelación
    #: de un quiz normal, y no sabría qué veredicto escribir.
    placement_round: str | None = None
    #: Cómo se le muestra el tema al estudiante (ver `DiagnosticPlan.label`).
    topic_label: str | None = None
    owner_id: UUID = field(default_factory=uuid4)
    questions: list[QuizQuestion] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utc_now)
    events: list[DomainEvent] = field(default_factory=list)

    @staticmethod
    def create(
        document_id: UUID | None,
        owner_id: UUID,
        questions: list[QuizQuestion],
        topic: str | None = None,
        placement_round: str | None = None,
        topic_label: str | None = None,
    ) -> "QuizAggregate":
        if not questions:
            raise ValueError("Un quiz debe tener al menos una pregunta")
        normalized: list[QuizQuestion] = []
        for q in questions:
            tags = getattr(q, "concept_tags", ()) or ()
            normalized.append(
                QuizQuestion(
                    text=q.text,
                    options=dict(q.options),
                    correct_answer=q.correct_answer,
                    difficulty=_normalize_difficulty(q.difficulty),
                    concept_tags=tuple(tags),
                    kind=getattr(q, "kind", "choice"),
                    key_points=tuple(getattr(q, "key_points", ()) or ()),
                    model_answer=getattr(q, "model_answer", "") or "",
                )
            )
        if document_id is None and not (topic or "").strip():
            raise ValueError("Un quiz necesita documento o tema: sin ninguno no se sabe qué evalúa.")
        quiz = QuizAggregate(
            document_id=document_id,
            topic=(topic or "").strip() or None,
            placement_round=placement_round,
            topic_label=topic_label,
            owner_id=owner_id,
            questions=normalized,
        )
        quiz.events.append(
            QuizGeneratedEvent(
                aggregate_id=quiz.id,
                document_id=document_id,
                owner_id=owner_id,
                num_questions=len(normalized),
            )
        )
        return quiz

    @property
    def total_points(self) -> int:
        return len(self.questions) * 10

    def is_owned_by(self, user_id: UUID) -> bool:
        return self.owner_id == user_id

    @property
    def open_indexes(self) -> tuple[int, ...]:
        return tuple(i for i, q in enumerate(self.questions) if q.is_open)

    def validate_answers(self, answers: dict[int, str]) -> None:
        """Un intento completo y con la forma de cada pregunta. Sin corregir nada."""
        n = len(self.questions)
        if len(answers) != n or any(i not in answers for i in range(n)):
            raise ValueError(
                f"Debes responder las {n} preguntas del cuestionario (intento incompleto)."
            )
        for index, choice in answers.items():
            if index < 0 or index >= n:
                raise ValueError(f"Índice de pregunta inválido: {index}")
            if self.questions[index].is_open:
                continue
            if choice not in self.questions[index].options:
                raise ValueError(
                    f"Opción '{choice}' no válida para la pregunta {index}"
                )

    def grade(self, answers: dict[int, str], open_grades: dict | None = None) -> QuizGrade:
        """Califica un intento completo. Requiere respuesta para cada pregunta.

        Las abiertas llegan ya corregidas (`open_grades`, ADR-052): corregirlas
        necesita al modelo y un agregado no hace I/O. Aquí solo se combinan, y una
        abierta sin corrección es un error, no un cero.
        """
        self.validate_answers(answers)
        open_grades = dict(open_grades or {})
        faltan = [i for i in self.open_indexes if i not in open_grades]
        if faltan:
            raise ValueError(f"Faltan las correcciones de las preguntas abiertas {faltan}.")
        n = len(self.questions)
        puntos: list[float] = []
        aciertos: list[bool] = []
        for i in range(n):
            q = self.questions[i]
            if q.is_open:
                g = open_grades[i]
                puntos.append(float(g.score))
                aciertos.append(bool(g.is_correct))
            else:
                ok = answers[i] == q.correct_answer
                puntos.append(1.0 if ok else 0.0)
                aciertos.append(ok)
        return QuizGrade(
            per_question_correct=tuple(aciertos),
            # Puntos enteros como siempre; una abierta parcial suma su parte.
            score=round(sum(puntos) * 10),
            total_points=self.total_points,
            per_question_score=tuple(round(p, 3) for p in puntos),
            open_grades={i: open_grades[i] for i in self.open_indexes},
        )

    def clear_events(self) -> None:
        self.events.clear()
