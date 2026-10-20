"""Puerta previa a OpenAI: dominio → caché → reuso → LLM."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

from src.domain.aggregates.document_aggregate import DocumentAggregate
from src.domain.ports.cache_port import CachePort
from src.domain.ports.ia_analyst import IAAnalyst
from src.domain.ports.metrics_port import MetricsPort
from src.domain.ports.repositories import QuizRepository
from src.domain.services.adaptive_policy import PromptShapingParameters
from src.domain.services.model_router import LlmTask, ModelRouter
from src.domain.services.pedagogical_engine import PedagogicalDecision
from src.domain.services.learner_context import LearnerContext
from src.domain.services.tutor_policy import TutorPolicy
from src.domain.value_objects.analysis_result import AnalysisResult
from src.domain.value_objects.question import Quiz

logger = logging.getLogger("laria.llm")


@dataclass
class LlmCallResult:
    payload: Any
    from_cache: bool
    model: str
    tokens_prompt: int = 0
    tokens_completion: int = 0


def _extras(
    learning_topic: str | None,
    history: tuple = (),
    quiz_request: str | None = None,
    learner: LearnerContext | None = None,
) -> dict:
    """Tema y conversación solo viajan si existen: así los analistas que no los
    conocen —fakes de test, proveedores futuros— siguen funcionando sin cambiar
    su firma."""
    extra: dict = {}
    if learning_topic:
        extra["learning_topic"] = learning_topic
    if history:
        extra["history"] = history
    # "" significa "pidió cuestionario sin tema": se distingue de None a propósito.
    if quiz_request is not None:
        extra["quiz_request"] = quiz_request
    if learner:
        extra["learner"] = learner
    return extra


class LlmGate:
    """Economía de tokens: evita llamadas innecesarias a OpenAI."""

    POLICY_VERSION = TutorPolicy.POLICY_VERSION

    def __init__(
        self,
        ia_analyst: IAAnalyst,
        cache: CachePort | None = None,
        model_router: ModelRouter | None = None,
        metrics: MetricsPort | None = None,
        quiz_repository: QuizRepository | None = None,
    ) -> None:
        self._ia = ia_analyst
        self._cache = cache
        self._router = model_router or ModelRouter()
        self._metrics = metrics
        self._quiz_repo = quiz_repository

    @staticmethod
    def _hash(*parts: str) -> str:
        h = hashlib.sha256()
        for p in parts:
            h.update((p or "").encode("utf-8"))
            h.update(b"|")
        return h.hexdigest()[:32]

    def _emit(self, name: str, **labels: str) -> None:
        if self._metrics:
            self._metrics.incr(name, **labels)

    def _observe_ms(self, name: str, started: float, **labels: str) -> None:
        if self._metrics:
            self._metrics.observe(name, (time.perf_counter() - started) * 1000.0, **labels)

    async def analyze(
        self,
        document: DocumentAggregate,
        *,
        force_refresh: bool = False,
    ) -> AnalysisResult:
        content_hash = self._hash(document.content or "")
        cache_key = f"analysis:{content_hash}"

        if not force_refresh and document.has_analysis():
            self._emit("laria_llm_skipped", task="analyze", reason="document_embedded")
            logger.info("analyze cache=document_embedded doc_id=%s", document.id)
            return document.analysis_result

        if not force_refresh and self._cache is not None:
            raw = await self._cache.get(cache_key)
            if raw:
                self._emit("laria_cache_hit", task="analyze")
                logger.info("analyze cache=hit key=%s", cache_key)
                data = json.loads(raw)
                return AnalysisResult(
                    summary=data.get("summary", ""),
                    key_concepts=list(data.get("key_concepts") or []),
                    suggested_questions=list(data.get("suggested_questions") or []),
                    confidence_score=float(data.get("confidence_score", 0.0) or 0.0),
                )

        choice = self._router.select(LlmTask.ANALYZE)
        logger.info("analyze cache=miss model=%s doc_id=%s", choice.model, document.id)
        started = time.perf_counter()
        result = await self._call_analyze(document, choice.model)
        self._observe_ms("laria_llm_latency_ms", started, task="analyze", model=choice.model)
        if self._cache is not None:
            await self._cache.set(
                cache_key,
                json.dumps(
                    {
                        "summary": result.summary,
                        "key_concepts": result.key_concepts,
                        "suggested_questions": result.suggested_questions,
                        "confidence_score": result.confidence_score,
                    },
                    ensure_ascii=False,
                ),
                ttl_seconds=86400 * 7,
            )
            self._emit("laria_cache_store", task="analyze")
        self._emit("laria_llm_calls", task="analyze", model=choice.model, outcome="ok")
        return result

    async def answer_question(
        self,
        context: str,
        question: str,
        decision: PedagogicalDecision | None = None,
        *,
        struggle_signals: int = 0,
        adaptation: PromptShapingParameters | None = None,
        learning_topic: str | None = None,
        history: tuple = (),
        quiz_request: str | None = None,
        learner: LearnerContext | None = None,
    ) -> str:
        choice = self._router.select(
            LlmTask.ASK, decision, struggle_signals=struggle_signals
        )
        policy = TutorPolicy()
        # Tema y conversación entran en el prompt y por tanto en la clave de
        # caché. Sin eso, "las guerras" en dos chats distintos devolvería la misma
        # respuesta cacheada, aunque en uno se hable de Roma y en otro de Grecia.
        prompt = policy.answer_question(
            context,
            question,
            decision,
            adaptation,
            learning_topic=learning_topic,
            history=history,
            quiz_request=quiz_request,
            learner=learner,
        )
        cache_key = f"prompt_resp:{self._hash(prompt.system, prompt.user, choice.model)}"

        if self._cache is not None:
            hit = await self._cache.get(cache_key)
            if hit:
                self._emit("laria_cache_hit", task="ask")
                logger.info("ask cache=hit model=%s", choice.model)
                return hit

        logger.info("ask cache=miss model=%s reason=%s", choice.model, choice.reason)
        started = time.perf_counter()
        answer = await self._call_answer(
            context, question, decision, choice.model, adaptation, learning_topic, history,
            quiz_request, learner,
        )
        self._observe_ms("laria_llm_latency_ms", started, task="ask", model=choice.model)
        if self._cache is not None:
            await self._cache.set(cache_key, answer, ttl_seconds=3600)
        self._emit("laria_llm_calls", task="ask", model=choice.model, outcome="ok")
        return answer

    async def answer_question_stream(
        self,
        context: str,
        question: str,
        decision: PedagogicalDecision | None = None,
        *,
        struggle_signals: int = 0,
        adaptation: PromptShapingParameters | None = None,
        learning_topic: str | None = None,
        history: tuple = (),
        quiz_request: str | None = None,
        learner: LearnerContext | None = None,
    ):
        """Streaming de la respuesta del tutor (yield de trozos de texto).

        Si hay respuesta en caché, hace yield del texto completo en un solo
        chunk. Si el proveedor no soporta streaming, delega a
        `answer_question` y emite una sola pieza.
        """
        choice = self._router.select(
            LlmTask.ASK, decision, struggle_signals=struggle_signals
        )
        policy = TutorPolicy()
        # Tema y conversación entran en el prompt y por tanto en la clave de
        # caché. Sin eso, "las guerras" en dos chats distintos devolvería la misma
        # respuesta cacheada, aunque en uno se hable de Roma y en otro de Grecia.
        prompt = policy.answer_question(
            context,
            question,
            decision,
            adaptation,
            learning_topic=learning_topic,
            history=history,
            quiz_request=quiz_request,
            learner=learner,
        )
        cache_key = f"prompt_resp:{self._hash(prompt.system, prompt.user, choice.model)}"

        if self._cache is not None:
            hit = await self._cache.get(cache_key)
            if hit:
                self._emit("laria_cache_hit", task="ask")
                yield hit
                return

        started = time.perf_counter()
        stream_fn = getattr(self._ia, "answer_question_stream", None)
        full = []
        if callable(stream_fn):
            async for token in stream_fn(
                context,
                question,
                decision,
                model=choice.model,
                adaptation=adaptation,
                **_extras(learning_topic, history, quiz_request, learner),
            ):
                full.append(token)
                yield token
        else:
            text = await self._call_answer(
                context, question, decision, choice.model, adaptation, learning_topic, history,
                quiz_request, learner,
            )
            full.append(text)
            yield text

        self._observe_ms("laria_llm_latency_ms", started, task="ask", model=choice.model)
        if self._cache is not None:
            await self._cache.set(cache_key, "".join(full), ttl_seconds=3600)
        self._emit("laria_llm_calls", task="ask", model=choice.model, outcome="ok")

    async def generate_quiz(
        self,
        document: DocumentAggregate,
        num_questions: int = 5,
        decision: PedagogicalDecision | None = None,
        context: str | None = None,
        student_id: UUID | None = None,
    ) -> Quiz:
        focus = ",".join(decision.focus_concepts) if decision else ""
        difficulty = decision.target_difficulty.value if decision else "medium"
        focus_hash = self._hash(focus, difficulty, self.POLICY_VERSION, str(num_questions))
        cache_key = f"quiz:{document.id}:{focus_hash}"

        # Reuso de quizzes similares del mismo documento
        if self._quiz_repo is not None and decision is not None:
            existing = await self._quiz_repo.find_by_document(document.id)
            for quiz in existing[:5]:
                if len(quiz.questions) != num_questions:
                    continue
                tags = set()
                for q in quiz.questions:
                    tags.update(t.lower() for t in (q.concept_tags or ()))
                focus_set = {c.lower() for c in decision.focus_concepts}
                if focus_set and tags & focus_set:
                    self._emit("laria_llm_skipped", task="quiz", reason="reuse_quiz")
                    return Quiz(questions=list(quiz.questions))

        if self._cache is not None:
            raw = await self._cache.get(cache_key)
            if raw:
                self._emit("laria_cache_hit", task="quiz")
                data = json.loads(raw)
                from src.domain.value_objects.question import QuizQuestion

                questions = [
                    QuizQuestion(
                        text=q["text"],
                        options=q["options"],
                        correct_answer=q["correct_answer"],
                        difficulty=q.get("difficulty", difficulty),
                        concept_tags=tuple(q.get("concept_tags") or ()),
                        kind=q.get("kind", "choice"),
                        key_points=tuple(q.get("key_points") or ()),
                        model_answer=q.get("model_answer", ""),
                    )
                    for q in data.get("questions", [])
                ]
                if questions:
                    return Quiz(questions=questions)

        choice = self._router.select(LlmTask.QUIZ, decision)
        quiz = await self._call_quiz(document, num_questions, decision, context, choice.model)
        if self._cache is not None:
            payload = {
                "questions": [
                    {
                        "text": q.text,
                        "options": q.options,
                        "correct_answer": q.correct_answer,
                        "difficulty": q.difficulty.value if hasattr(q.difficulty, "value") else q.difficulty,
                        "concept_tags": list(q.concept_tags or ()),
                        "kind": q.kind,
                        "key_points": list(q.key_points),
                        "model_answer": q.model_answer,
                    }
                    for q in quiz.questions
                ]
            }
            await self._cache.set(cache_key, json.dumps(payload, ensure_ascii=False), ttl_seconds=86400)
        self._emit("laria_llm_calls", task="quiz", model=choice.model, outcome="ok")
        return quiz

    async def invalidate_document(self, document_id: UUID, content: str = "") -> None:
        if self._cache is None:
            return
        if content:
            await self._cache.delete(f"analysis:{self._hash(content)}")
        await self._cache.delete_prefix(f"quiz:{document_id}:")

    async def _call_analyze(self, document: DocumentAggregate, model: str) -> AnalysisResult:
        # Prefer analyst hook with model if available
        analyze = getattr(self._ia, "analyze_with_model", None)
        if callable(analyze):
            return await analyze(document, model=model)
        return await self._ia.analyze(document)

    async def _call_answer(
        self,
        context: str,
        question: str,
        decision: PedagogicalDecision | None,
        model: str,
        adaptation: PromptShapingParameters | None = None,
        learning_topic: str | None = None,
        history: tuple = (),
        quiz_request: str | None = None,
        learner: LearnerContext | None = None,
    ) -> str:
        extra = _extras(learning_topic, history, quiz_request, learner)
        fn = getattr(self._ia, "answer_question_with_model", None)
        if callable(fn):
            return await fn(
                context, question, decision, model=model, adaptation=adaptation, **extra
            )
        return await self._ia.answer_question(context, question, decision, adaptation, **extra)

    async def _call_quiz(
        self,
        document: DocumentAggregate,
        num_questions: int,
        decision: PedagogicalDecision | None,
        context: Optional[str],
        model: str,
    ) -> Quiz:
        fn = getattr(self._ia, "generate_quiz_with_model", None)
        if callable(fn):
            return await fn(document, num_questions, decision, context, model=model)
        return await self._ia.generate_quiz(document, num_questions, decision, context)
