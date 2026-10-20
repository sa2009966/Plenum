"""Puerto del juez de respuestas abiertas (ADR-052).

Solo juzga la rúbrica idea por idea; la nota la calcula el dominio
(`open_answers.grade_from_rubric`).
"""
from abc import ABC, abstractmethod

from src.domain.open_answers import OpenQuestion, RubricJudgement


class OpenAnswerJudge(ABC):
    @abstractmethod
    async def judge(self, question: OpenQuestion, answer: str) -> RubricJudgement:
        ...
