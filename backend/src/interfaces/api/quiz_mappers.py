"""Helpers compartidos para mapear DTOs/aggregados de quiz a schemas HTTP."""
from src.interfaces.schemas.quiz_schemas import (
    AttemptQuestionResultItem,
    KeyPointResult,
    QuizPublicResponse,
    QuizQuestionPublicItem,
)


def quiz_to_public_response(quiz) -> QuizPublicResponse:
    return QuizPublicResponse(
        id=str(quiz.id),
        document_id=str(quiz.document_id) if quiz.document_id else None,
        topic=getattr(quiz, "topic", None),
        topic_label=getattr(quiz, "topic_label", None),
        questions=[
            QuizQuestionPublicItem(
                # DTO (trae `index`) o agregado (posición en la lista): los dos sirven.
                index=getattr(q, "index", i),
                text=q.text,
                options=q.options,
                difficulty=getattr(q.difficulty, "value", q.difficulty),
                kind=getattr(q, "kind", "choice"),
                max_chars=getattr(q, "max_chars", None)
                if hasattr(q, "max_chars")
                else (_MAX if getattr(q, "kind", "choice") == "open" else None),
            )
            for i, q in enumerate(quiz.questions)
        ],
        total_points=quiz.total_points,
        created_at=quiz.created_at,
    )


from src.domain.open_answers import MAX_ANSWER_CHARS as _MAX  # noqa: E402


def attempt_question_item(q) -> AttemptQuestionResultItem:
    """Resultado de una pregunta, igual en /quizzes/{id}/attempts y en /check (ADR-053)."""
    return AttemptQuestionResultItem(
        index=q.index,
        text=q.text,
        selected=q.selected,
        correct_answer=q.correct_answer,
        is_correct=q.is_correct,
        kind=getattr(q, "kind", "choice"),
        score=getattr(q, "score", 1.0 if q.is_correct else 0.0),
        verdict=getattr(q, "verdict", None),
        feedback=getattr(q, "feedback", None),
        key_points=(
            [KeyPointResult(text=t, covered=c) for t, c in q.key_points]
            if getattr(q, "key_points", None) is not None
            else None
        ),
        model_answer=getattr(q, "model_answer", None),
    )
