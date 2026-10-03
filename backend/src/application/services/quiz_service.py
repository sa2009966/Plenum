from typing import Optional
from uuid import UUID

from src.application.concurrency import with_concurrency_retry
from src.application.dto.quiz_dto import (
    PlacementResultDTO,
    AttemptQuestionResultDTO,
    QuizAttemptResultDTO,
    QuizPublicDTO,
    QuizQuestionPublicDTO,
)
from src.domain.aggregates.quiz_aggregate import QuizAggregate
from src.domain.catalog.prerequisite_seeds import build_seeded_graph
from src.domain.concept_identity import canonicalize_concept
from src.domain.aggregates.quiz_attempt_aggregate import QuizAttemptAggregate
from src.domain.aggregates.tutor_session import TutorSession
from src.domain.ports.event_bus import EventBus
from src.domain.ports.ia_analyst import IAAnalyst
from src.domain.ports.repositories import (
    ConceptGraphRepository,
    DocumentRepository,
    QuizAttemptRepository,
    QuizRepository,
    StudentProfileRepository,
    TutorInteractionRepository,
    TutorSessionRepository,
)
from src.application.services.llm_gate import LlmGate
from src.domain.services.concept_tagger import ConceptTagger
from src.domain.services.context_selector import ContextSelector
from src.domain.services.diagnostic_planner import (
    PASSING_RATIO,
    PlacementLevel,
    PlacementRound,
    has_next_round,
    plan_diagnostic,
    plan_practice,
    resolve_placement,
    round_for,
)
from src.domain.services.pedagogical_engine import PedagogicalEngine, TutorIntent
from src.domain.services.quiz_quality import ensure_quiz_quality
from src.domain.value_objects.question import Difficulty


def repeated_questions(preguntas, previas: tuple[str, ...], umbral: float = 0.75) -> int:
    """Cuántas preguntas repiten (casi literalmente) una de `previas`."""
    from difflib import SequenceMatcher

    viejas = [p.lower() for p in previas]
    return sum(
        1 for q in preguntas
        if any(SequenceMatcher(None, q.text.lower(), v).ratio() > umbral for v in viejas)
    )


class QuizService:
    _MSG_PERMISO = "No tienes permiso para operar sobre este quiz"
    _MSG_QUIZ_NO_ENCONTRADO = "Quiz no encontrado"
    _MSG_DOC_NO_ENCONTRADO = "Documento no encontrado"
    _MSG_DOC_PERMISO = "No tienes permiso para operar sobre este documento"
    _MSG_TEMA_VACIO = "Dime qué tema quieres aprender para poder evaluarte."

    def __init__(
        self,
        document_repository: DocumentRepository,
        quiz_repository: QuizRepository,
        attempt_repository: QuizAttemptRepository,
        interaction_repository: TutorInteractionRepository,
        ia_analyst: Optional[IAAnalyst] = None,
        event_bus: Optional[EventBus] = None,
        profile_repository: Optional[StudentProfileRepository] = None,
        pedagogical_engine: Optional[PedagogicalEngine] = None,
        session_repository: Optional[TutorSessionRepository] = None,
        llm_gate: Optional[LlmGate] = None,
        concept_graph_repository: Optional[ConceptGraphRepository] = None,
        graph_id: str = "default",
        analyze_service=None,
        strong_model: Optional[str] = None,
        safety=None,
    ) -> None:
        self._doc_repo = document_repository
        # Filtro de temas (ADR-036): una nivelación o práctica crea contenido sobre el tema.
        self._safety = safety
        self._quiz_repo = quiz_repository
        self._attempt_repo = attempt_repository
        self._interaction_repo = interaction_repository
        self._ia_analyst = ia_analyst
        self._event_bus = event_bus
        self._profile_repo = profile_repository
        self._engine = pedagogical_engine or PedagogicalEngine()
        self._session_repo = session_repository
        self._graph_repo = concept_graph_repository
        # Para asegurar el análisis antes de un quiz sobre un documento (ADR-029).
        self._analyze = analyze_service
        # Modelo para la ronda avanzada: con el barato, las "difíciles" medían
        # nivel cognitivo 2.08/3 y la nivelación sobreestimaba (ADR-031).
        self._strong_model = strong_model
        self._graph_id = graph_id
        self._tagger = ConceptTagger()
        self._context = ContextSelector()
        self._llm_gate = llm_gate

    async def generate(
        self,
        document_id: UUID,
        user_id: UUID,
        num_questions: int = 5,
    ) -> QuizPublicDTO:
        document = await self._doc_repo.find_by_id(document_id)
        if document is None:
            raise ValueError(self._MSG_DOC_NO_ENCONTRADO)
        if not document.is_owned_by(user_id):
            raise PermissionError(self._MSG_DOC_PERMISO)
        if not document.content:
            body = await self._doc_repo.get_content(document_id)
            if body is None:
                raise ValueError(self._MSG_DOC_NO_ENCONTRADO)
            document.content = body
        if self._ia_analyst is None and self._llm_gate is None:
            raise ValueError("IA Analyst not configured")
        if self._analyze is not None:
            # Sin análisis, el quiz no sabe de qué conceptos va el documento.
            document = await self._analyze.ensure_analysis(document, user_id)

        profile = None
        if self._profile_repo is not None:
            profile = await self._profile_repo.find_by_student(user_id)
        session = None
        if self._session_repo is not None:
            session = await self._session_repo.find_by_student_document(user_id, document_id)
        concepts = ()
        if document.has_analysis() and document.analysis_result is not None:
            concepts = tuple(document.analysis_result.key_concepts or ())
        graph = None
        if self._graph_repo is not None:
            graph = await self._graph_repo.find_by_id(self._graph_id)
        decision = self._engine.select(
            profile, document_id, TutorIntent.QUIZ, concepts, session=session, graph=graph
        )
        # Repartido por todo el documento si no hay foco: un quiz de un libro no
        # debe salir solo de las primeras páginas (ADR-029).
        ctx = self._context.select(document, decision.focus_concepts, max_chars=8000, spread=True)
        if self._llm_gate is not None:
            generated = await self._llm_gate.generate_quiz(
                document,
                num_questions,
                decision=decision,
                context=ctx,
                student_id=user_id,
            )
        else:
            generated = await self._ia_analyst.generate_quiz(
                document, num_questions, decision=decision, context=ctx
            )

        questions = ensure_quiz_quality(list(generated.questions))
        questions = self._tagger.tag_questions(
            questions, concepts or decision.focus_concepts, subject=document.subject
        )
        quiz = QuizAggregate.create(document_id, user_id, questions)
        await self._quiz_repo.save(quiz)

        if self._event_bus:
            for event in quiz.events:
                await self._event_bus.publish(event)
        quiz.clear_events()

        return self._to_public_dto(quiz)

    async def generate_diagnostic(self, topic: str, user_id: UUID) -> QuizPublicDTO:
        """Diagnóstico de entrada sobre un tema, sin material (ADR-016).

        Lo que el estudiante pide diciendo "quiero aprender ecuaciones": una
        escalera de ítems fáciles, medios y difíciles que mide qué sabe ya —del
        tema y de su base— para que el motor deje de estar ciego desde el primer
        turno en vez de desde el quinto.
        """
        await self._tema_seguro(topic)
        graph, nivel = await self._grafo_y_nivel(topic, user_id)
        # La ronda no la manda el cliente: sale del nivel que el estudiante ya
        # tenga en ese tema. Así el cliente no lleva estado (ADR-017, decisión 4).
        ronda = round_for(nivel)
        return await self._quiz_por_tema(plan_diagnostic(topic, graph, ronda), user_id)

    async def generate_practice(
        self, topic: str, user_id: UUID, num_questions: int = 5
    ) -> QuizPublicDTO:
        """Cuestionario de práctica sobre un tema, sin material.

        Lo que el estudiante pide diciendo "ponme un quiz de fracciones". Antes el
        tutor lo escribía como texto en el chat: no se corregía en el servidor ni
        dejaba evidencia. Aquí se corrige como cualquier quiz y la evidencia cuenta,
        pero NO cambia el nivel guardado: practicar no es nivelarse. La dificultad
        se ajusta al nivel que ya tenga en el tema.
        """
        await self._tema_seguro(topic)
        graph, nivel = await self._grafo_y_nivel(topic, user_id)
        plan = plan_practice(topic, graph, nivel, num_questions)
        return await self._quiz_por_tema(plan, user_id)

    async def _tema_seguro(self, topic: str) -> None:
        if self._safety is not None:
            await self._safety.ensure_safe_topic(topic)

    async def _grafo_y_nivel(self, topic: str, user_id: UUID):
        """El currículum y el nivel que el estudiante ya tiene en ese tema.

        El nivel se busca por el tema CANÓNICO, que es con el que se guardó. El
        alumno escribe "ecuaciones" y el currículum lo resuelve a "ecuaciones
        lineales": buscando por lo escrito no se encontraba nunca, y el
        estudiante recibía la ronda básica una y otra vez sin avanzar jamás.
        """
        if not (topic or "").strip():
            raise ValueError(self._MSG_TEMA_VACIO)
        if self._ia_analyst is None:
            raise ValueError("IA Analyst not configured")
        graph = None
        if self._graph_repo is not None:
            graph = await self._graph_repo.find_by_id(self._graph_id)
        if graph is None:
            graph = build_seeded_graph(self._graph_id)
        tema = graph.canonicalize(canonicalize_concept(topic))
        nivel = None
        if self._profile_repo is not None:
            perfil = await self._profile_repo.find_by_student(user_id)
            if perfil is not None:
                guardado = perfil.level_for_topic(tema)
                nivel = PlacementLevel(guardado) if guardado else None
        return graph, nivel

    #: Preguntas recientes del tema que no se deben repetir (ADR-031).
    _MAX_PREVIAS = 30

    async def _preguntas_previas(self, user_id: UUID, topic: str) -> tuple[str, ...]:
        """Enunciados de nivelaciones y prácticas anteriores del mismo tema."""
        try:
            quizzes = await self._quiz_repo.find_by_owner(user_id)
        except Exception:  # noqa: BLE001 — sin historial, se genera igual
            return ()
        mismos = sorted(
            (q for q in quizzes if q.document_id is None and q.topic == topic),
            key=lambda q: q.created_at,
            reverse=True,
        )
        return tuple(p.text for q in mismos for p in q.questions)[: self._MAX_PREVIAS]

    async def _generar_sin_repetir(self, plan, previas: tuple[str, ...]):
        """Genera pidiendo no repetir; si aun así repite, lo vuelve a intentar una vez.

        Medido: sin esto, un tercio de la ronda avanzada repetía preguntas de la
        base (14/42), y el estudiante contestaba lo mismo dos veces.
        """
        kwargs: dict = {"avoid": previas} if previas else {}
        if self._strong_model and getattr(plan, "round", None) == PlacementRound.AVANZADA:
            kwargs["model"] = self._strong_model
        try:
            generado = await self._ia_analyst.generate_diagnostic(plan, **kwargs)
        except TypeError:  # analistas sin `avoid` (dobles de prueba antiguos)
            return await self._ia_analyst.generate_diagnostic(plan)
        if previas and repeated_questions(generado.questions, previas) > 0:
            otra = await self._ia_analyst.generate_diagnostic(plan, **kwargs)
            if repeated_questions(otra.questions, previas) < repeated_questions(generado.questions, previas):
                generado = otra
        return generado

    async def _quiz_por_tema(self, plan, user_id: UUID) -> QuizPublicDTO:
        """Genera, etiqueta y guarda un quiz sin documento. Nivelación o práctica:
        lo distingue `plan.round` (None = práctica, que no escribe nivel)."""
        previas = await self._preguntas_previas(user_id, plan.topic)
        generated = await self._generar_sin_repetir(plan, previas)
        questions = ensure_quiz_quality(list(generated.questions))
        # Red de seguridad: el prompt pide concept_tags, pero si el modelo los
        # omite la evidencia se perdería sin que nadie lo note.
        questions = self._tagger.tag_questions(questions, plan.concepts)
        quiz = QuizAggregate.create(
            None,
            user_id,
            questions,
            topic=plan.topic,
            placement_round=plan.round.value if plan.round else None,
            topic_label=plan.label,
        )
        await self._quiz_repo.save(quiz)

        if self._event_bus:
            for event in quiz.events:
                await self._event_bus.publish(event)
        quiz.clear_events()

        return self._to_public_dto(quiz)

    async def get_quiz(self, quiz_id: UUID, user_id: UUID) -> QuizPublicDTO:
        quiz = await self._get_quiz_if_owner(quiz_id, user_id)
        return self._to_public_dto(quiz)

    async def submit_attempt(
        self,
        quiz_id: UUID,
        user_id: UUID,
        answers: dict[int, str],
    ) -> QuizAttemptResultDTO:
        quiz = await self._get_quiz_if_owner(quiz_id, user_id)
        grade = quiz.grade(answers)
        attempt = QuizAttemptAggregate.create(
            quiz_id=quiz.id,
            document_id=quiz.document_id,
            student_id=user_id,
            answers=answers,
            grade=grade,
        )
        await self._attempt_repo.save(attempt)

        if self._event_bus:
            for event in attempt.events:
                await self._event_bus.publish(event)
        attempt.clear_events()

        ratio = (attempt.score / attempt.total_points) if attempt.total_points else 0.0

        # Una sesión de tutoría es por (estudiante, documento): sin documento no
        # hay sesión que actualizar. Sin esta guarda, una ronda de nivelación
        # buscaba la sesión de `None` y rompía en producción.
        if self._session_repo is not None and quiz.document_id is not None:

            async def _persist_session():
                session = await self._session_repo.find_by_student_document(
                    user_id, quiz.document_id
                )
                if session is None:
                    session = TutorSession.start(user_id, quiz.document_id)
                session.record_quiz_check(ratio)
                await self._session_repo.save(session)
                return session

            await with_concurrency_retry(_persist_session)

        return QuizAttemptResultDTO(
            attempt_id=attempt.id,
            quiz_id=quiz.id,
            document_id=quiz.document_id,
            placement=await self._veredicto(quiz, user_id, ratio),
            score=attempt.score,
            total_points=attempt.total_points,
            questions=[
                AttemptQuestionResultDTO(
                    index=i,
                    text=q.text,
                    selected=answers.get(i),
                    correct_answer=q.correct_answer,
                    is_correct=attempt.per_question_correct[i],
                )
                for i, q in enumerate(quiz.questions)
            ],
            completed_at=attempt.completed_at,
        )

    async def _get_quiz_if_owner(self, quiz_id: UUID, user_id: UUID) -> QuizAggregate:
        quiz = await self._quiz_repo.find_by_id(quiz_id)
        if quiz is None:
            raise ValueError(self._MSG_QUIZ_NO_ENCONTRADO)
        if not quiz.is_owned_by(user_id):
            raise PermissionError(self._MSG_PERMISO)
        return quiz

    @staticmethod
    def _difficulty_str(value) -> str:
        if isinstance(value, Difficulty):
            return value.value
        return str(value)

    async def _veredicto(
        self, quiz: QuizAggregate, user_id: UUID, ratio: float
    ) -> PlacementResultDTO | None:
        """Veredicto de la ronda, para que el cliente sepa si queda otra.

        Calcula lo mismo que el projector escribirá en el perfil, con la misma
        función pura. No lo escribe: el perfil tiene un único escritor
        (invariante 1) y el evento ya va de camino.
        """
        if not quiz.topic or not quiz.placement_round:
            return None
        ronda = PlacementRound(quiz.placement_round)
        previo = None
        if self._profile_repo is not None:
            perfil = await self._profile_repo.find_by_student(user_id)
            if perfil is not None:
                guardado = perfil.level_for_topic(quiz.topic)
                previo = PlacementLevel(guardado) if guardado else None
        nivel = resolve_placement(ronda, ratio, previo)
        return PlacementResultDTO(
            topic=quiz.topic,
            topic_label=quiz.topic_label or quiz.topic,
            round=ronda.value,
            level=nivel.value,
            passed=ratio >= PASSING_RATIO,
            has_next_round=has_next_round(ronda, nivel),
        )

    def _to_public_dto(self, quiz: QuizAggregate) -> QuizPublicDTO:
        return QuizPublicDTO(
            id=quiz.id,
            document_id=quiz.document_id,
            topic=quiz.topic,
            topic_label=quiz.topic_label,
            questions=[
                QuizQuestionPublicDTO(
                    index=i,
                    text=q.text,
                    options=dict(q.options),
                    difficulty=self._difficulty_str(q.difficulty),
                )
                for i, q in enumerate(quiz.questions)
            ],
            total_points=quiz.total_points,
            created_at=quiz.created_at,
        )
