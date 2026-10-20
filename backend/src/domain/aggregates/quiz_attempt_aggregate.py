from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4

from src.domain.aggregates.quiz_aggregate import QuizGrade
from src.domain.events.domain_events import DomainEvent, QuizAttemptCompletedEvent


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class QuizAttemptAggregate:
    id: UUID = field(default_factory=uuid4)
    quiz_id: UUID = field(default_factory=uuid4)
    document_id: UUID | None = None
    student_id: UUID = field(default_factory=uuid4)
    answers: dict[int, str] = field(default_factory=dict)
    per_question_correct: list[bool] = field(default_factory=list)
    #: Crédito 0..1 por pregunta (ADR-053); vacío en intentos anteriores.
    per_question_score: list[float] = field(default_factory=list)
    #: Índice → {verdict, score, covered, feedback} de cada abierta corregida.
    open_results: dict[int, dict] = field(default_factory=dict)
    score: int = 0
    total_points: int = 0
    completed_at: datetime = field(default_factory=_utc_now)
    events: list[DomainEvent] = field(default_factory=list)

    @staticmethod
    def create(
        quiz_id: UUID,
        document_id: UUID | None,
        student_id: UUID,
        answers: dict[int, str],
        grade: QuizGrade,
    ) -> "QuizAttemptAggregate":
        attempt = QuizAttemptAggregate(
            quiz_id=quiz_id,
            document_id=document_id,
            student_id=student_id,
            answers=dict(answers),
            per_question_correct=list(grade.per_question_correct),
            per_question_score=list(grade.per_question_score),
            open_results={
                i: {
                    "verdict": g.verdict.value,
                    "score": g.score,
                    "covered": list(g.covered),
                    "feedback": g.feedback,
                }
                for i, g in grade.open_grades.items()
            },
            score=grade.score,
            total_points=grade.total_points,
        )
        attempt.events.append(
            QuizAttemptCompletedEvent(
                aggregate_id=attempt.id,
                quiz_id=quiz_id,
                document_id=document_id,
                student_id=student_id,
                score=grade.score,
                total=grade.total_points,
            )
        )
        return attempt

    def score_at(self, i: int) -> float:
        """Crédito de la pregunta i; en intentos anteriores, 1 o 0 según acertó."""
        if i < len(self.per_question_score):
            return float(self.per_question_score[i])
        return 1.0 if i < len(self.per_question_correct) and self.per_question_correct[i] else 0.0

    def clear_events(self) -> None:
        self.events.clear()
