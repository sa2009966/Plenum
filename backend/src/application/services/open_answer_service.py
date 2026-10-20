"""Corregir una respuesta abierta (ADR-052).

Primero lo que el dominio decide solo (vacía, copia del ejemplo, repetir el
enunciado); después el juez, idea por idea; la nota la calcula el dominio. Si el
juez devuelve algo que no encaja con la rúbrica, se le pregunta una vez más: una
respuesta del estudiante no puede quedarse sin corregir por un JSON mal formado,
pero tampoco se inventa una nota.
"""
from __future__ import annotations

import logging

from src.domain.open_answers import (
    MAX_ANSWER_CHARS,
    OpenAnswerGrade,
    OpenQuestion,
    grade_from_rubric,
    precheck,
)
from src.domain.ports.ia_analyst import IAAnalysisError
from src.domain.ports.open_answer_judge import OpenAnswerJudge

logger = logging.getLogger("laria.open_answers")


class OpenAnswerGradingService:
    def __init__(self, judge: OpenAnswerJudge) -> None:
        self._judge = judge

    async def grade(self, question: OpenQuestion, answer: str) -> OpenAnswerGrade:
        respuesta = (answer or "").strip()[:MAX_ANSWER_CHARS]
        previa = precheck(question, respuesta)
        if previa is not None:
            return previa
        for intento in (1, 2):
            try:
                return grade_from_rubric(question, await self._judge.judge(question, respuesta), respuesta)
            except (IAAnalysisError, ValueError) as exc:
                if intento == 2:
                    # 502 y no 500: es el proveedor el que no respondió algo corregible.
                    raise IAAnalysisError("No se pudo corregir la respuesta ahora mismo.") from exc
                logger.warning("juez_respuesta_invalida_reintento")
        raise IAAnalysisError("inalcanzable")
