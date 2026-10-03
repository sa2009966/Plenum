"""Servicio de tutoría para chats: orquesta el motor pedagógico o el modo libre."""
from dataclasses import dataclass, replace
from typing import Optional
from uuid import UUID

from src.application.services.analyze_document_service import AnalyzeDocumentService
from src.application.services.content_safety_service import ContentSafetyService
from src.application.services.learning_preferences_service import LearningPreferencesService
from src.application.services.llm_gate import LlmGate
from src.application.services.topic_catalog import TopicCatalog
from src.domain.ports.repositories import (
    DocumentRepository,
    StudentProfileRepository,
)
from src.domain.aggregates.student_profile import StudentProfile
from src.domain.services.adaptive_policy import AdaptationParameters
from src.domain.catalog.voices import persona_for
from src.domain.services.affect_policy import AffectPolicy
from src.domain.services.content_safety import SafetyAction, safety_message
from src.domain.services.cognitive_style import CognitiveStyle, chosen_style, style_requested_in
from src.domain.services.intent_detector import IntentDetector, TutorIntent
from src.domain.services.learner_context import (
    MAX_LEVELS_IN_PROMPT,
    LearnerContext,
    style_from_option_reply,
    tutor_offered_styles,
)
from src.domain.services.pedagogical_engine import (
    PedagogicalDecision,
    PedagogicalMode,
)
from src.domain.services.prerequisite_graph import GateAction
from src.domain.services.response_envelope import (
    EnvelopeType,
    ResponseEnvelope,
    envelope_type_for_mode,
    plain_envelope,
)
from src.domain.ports.embodiment import AffectState


def _control_flow_payload(adaptation: AdaptationParameters) -> dict:
    """Pistas de orquestación para el cliente, con y sin streaming.

    `chunk_explanation` solo lo puede aplicar quien pinta. `practice_before_advance`
    **ya viene aplicado en el prompt** desde el ADR-015 y se sigue emitiendo para
    que la UI pueda destacar el ejercicio: es información, no una orden.
    """
    return {
        "practice_before_advance": adaptation.prompt_shaping.practice_before_advance,
        "chunk_explanation": adaptation.control_flow.chunk_explanation,
    }


def _tema_a_ofrecer(intention) -> str | None:
    """El tema para el que el tutor ofrecerá nivelación, si el estudiante pidió
    aprender uno. Misma condición que `suggest_placement`: el texto del tutor y la
    oferta que pinta el cliente no pueden decir cosas distintas (ADR-017)."""
    return intention.topic_hint if intention.suggest_placement else None


def _cuestionario_pedido(intention) -> str | None:
    """Qué cuestionario pidió: None si ninguno, "" si no dijo de qué, o el tema.
    Misma condición que `offer_quiz`: el texto del tutor y la tarjeta del
    cliente no pueden decir cosas distintas."""
    return (intention.topic_hint or "") if intention.offer_quiz else None


def _intent_payload(intention) -> dict:
    """Intención del turno, y si el estudiante pidió aprender un tema.

    `intent` puede ser `learn` con cualquier pregunta conceptual ("qué es…"), así
    que no sirve para decidir cuándo ofrecer nivelación. `suggest_placement` solo
    aparece cuando pidió aprender un TEMA, y `topic_hint` trae ese tema tal como lo
    escribió: con sus tildes, para mostrárselo (ADR-017).
    """
    carga: dict = {"intent": intention.intent.value}
    if intention.topic_hint:
        carga["topic_hint"] = intention.topic_hint
    if intention.suggest_placement:
        carga["suggest_placement"] = True
    # Pidió un cuestionario o practicar: el cliente abre uno interactivo, que se
    # corrige en el servidor. Más estrecho que `intent == "quiz"` nunca fue.
    if intention.offer_quiz:
        carga["offer_quiz"] = True
    # Pidió que se le pregunte cómo aprende: el cliente puede mostrar la tarjeta
    # de estilos además del texto del tutor (ADR-023).
    if intention.ask_learning_style:
        carga["ask_learning_style"] = True
    return carga


def _is_remediation(decision: Optional[PedagogicalDecision]) -> bool:
    """Si el turno está remediando, no es momento de celebrar nada."""
    if decision is None:
        return False
    return (
        decision.mode == PedagogicalMode.SCAFFOLD
        or decision.gate_action == GateAction.SEQUENCE
    )


def _milestone(
    profile: Optional[StudentProfile], decision: Optional[PedagogicalDecision]
) -> Optional[str]:
    """Concepto dominado y aún no reconocido, si el turno admite celebrarlo.

    El canal positivo existía y estaba muerto: ningún modo mapeaba a
    `celebration` y nadie pasaba `last_score_ratio`, así que `CELEBRATORY` era
    inalcanzable. Hacer visible lo logrado es el P4 del plan (ADR-009).
    """
    if profile is None or _is_remediation(decision):
        return None
    return profile.pending_celebration()


def _last_graded_ratio(
    profile: Optional[StudentProfile],
    document_id: Optional[UUID],
    decision: Optional[PedagogicalDecision],
) -> Optional[float]:
    """Último acierto **calificado** del documento, si el turno admite tono alto.

    Exige `attempts > 0`: un documento sin quizzes tiene `last_score_ratio`
    en 0.0 por defecto y leerlo sería inventar un mal resultado (ADR-007).
    """
    if profile is None or document_id is None or _is_remediation(decision):
        return None
    entry = profile.mastery_by_document.get(document_id)
    if entry is None or entry.attempts == 0:
        return None
    return entry.last_score_ratio


def _envelope_type(
    decision: Optional[PedagogicalDecision], milestone: Optional[str]
) -> EnvelopeType:
    if milestone:
        return "celebration"
    return envelope_type_for_mode(decision.mode if decision else None)


@dataclass(frozen=True)
class TutorResponse:
    """Respuesta del tutor: texto + envelope para la UI (tipo/emoción/payload)."""

    content: str
    envelope: ResponseEnvelope


def _estilo_elegido(eleccion: tuple[bool, str | None]) -> dict:
    """Eligió estilo en el chat: el cliente lo refleja sin volver a pedirlo (ADR-023)."""
    eligio, estilo = eleccion
    return {"explanation_style_chosen": estilo} if eligio else {}


def _nivel_conocido(extra: dict, learner: LearnerContext | None) -> dict:
    """Si ya se niveló en el tema que pide, no se ofrece otra nivelación (ADR-022).

    El tutor empieza la clase desde su nivel; el botón de "nivelarme" contradiría
    lo que dice. El cliente recibe el nivel para mostrarlo.
    """
    if learner is None or learner.topic_level is None:
        return extra
    extra = {k: v for k, v in extra.items() if k != "suggest_placement"}
    extra["placement_level"] = learner.topic_level[1]
    return extra


class ChatTutorService:
    """Responde mensajes de chat: usa el motor pedagógico si hay documento vinculado,
    o modo libre (LlmGate directo) si es conversación general."""

    def __init__(
        self,
        analyze_service: Optional[AnalyzeDocumentService] = None,
        llm_gate: Optional[LlmGate] = None,
        document_repository: Optional[DocumentRepository] = None,
        profile_repository: Optional[StudentProfileRepository] = None,
        topic_catalog: Optional[TopicCatalog] = None,
        preferences: Optional[LearningPreferencesService] = None,
        safety: Optional[ContentSafetyService] = None,
    ) -> None:
        self._analyze_service = analyze_service
        self._llm_gate = llm_gate
        self._doc_repo = document_repository
        self._profile_repo = profile_repository
        self._topics = topic_catalog
        self._preferences = preferences
        self._safety = safety
        self._affect = AffectPolicy()
        self._intent = IntentDetector()

    async def _eleccion_de_estilo(
        self, intention, question: str, history: tuple, student_id: UUID
    ) -> tuple[bool, str | None]:
        """Si en este turno dijo cómo prefiere aprender: `(eligió, estilo)`. Lo guarda.

        Vale una declaración ("me siento más cómodo con esquemas") o la respuesta a
        las opciones que el tutor acaba de ofrecer ("la 4"). Estilo None = que
        decida LARIA. Se guarda por el mismo camino que la tarjeta del cliente:
        evento y projector (ADR-023).
        """
        if intention.declared_style:
            eligio, estilo = True, intention.declared_style
        else:
            ultimo = next((t for rol, t in reversed(history) if rol == "assistant"), "")
            eligio, estilo = (
                style_from_option_reply(question)
                if tutor_offered_styles(ultimo) and len(question) < 120
                else (False, None)
            )
        if eligio and self._preferences is not None:
            await self._preferences.choose_explanation_style(student_id, estilo)
        return eligio, estilo

    async def _learner(
        self,
        profile: StudentProfile | None,
        intention,
        question: str,
        eleccion: tuple[bool, str | None] = (False, None),
    ) -> LearnerContext | None:
        """Nivel y estilo para el modo libre (ADR-022). None si no hay nada que usar."""
        eligio, elegido = eleccion
        if eligio:
            # El perfil se leyó antes de guardar la elección: manda la de ahora.
            style = CognitiveStyle(elegido) if elegido else None
        else:
            style = style_requested_in(question) or chosen_style(profile)
        base = LearnerContext(
            style=style,
            ask_style=intention.ask_learning_style,
            style_just_chosen=eligio,
            persona=persona_for(profile.voice_choice if profile else None),
        )
        if base.ask_style or profile is None or not profile.level_by_topic:
            return base or None
        tema = _tema_a_ofrecer(intention)
        if tema:
            clave = await self._topics.canonical(tema) if self._topics else tema
            nivel = profile.level_for_topic(clave)
            if nivel:
                etiqueta = profile.label_for_topic(clave) or tema
                return replace(base, topic_level=(etiqueta, nivel))
        # Sin tema concreto: los últimos temas nivelados, para que el modelo
        # ajuste la profundidad si la pregunta cae en uno de ellos.
        niveles = tuple(
            (profile.topic_labels.get(clave, clave), nivel)
            for clave, nivel in list(profile.level_by_topic.items())[-MAX_LEVELS_IN_PROMPT:]
        )
        return replace(base, levels=niveles)

    async def _respuesta_de_seguridad(
        self, question: str, document_id: Optional[UUID]
    ) -> TutorResponse | None:
        """Si el mensaje no se trabaja (ADR-036), la respuesta fija; si se trabaja, None.

        Va antes del modelo y del motor: un mensaje rechazado no gasta tokens ni deja
        evidencia, y la autolesión recibe siempre la misma respuesta cuidada, no lo que
        el modelo improvise.
        """
        if self._safety is None:
            return None
        veredicto = await self._safety.verdict(question)
        if veredicto.allowed:
            return None
        texto = safety_message(veredicto)
        envelope = plain_envelope(
            "answer",
            texto,
            grounded=document_id is not None,
            emotion=AffectState.CALM
            if veredicto.action is SafetyAction.SUPPORT
            else AffectState.PATIENT,
        )
        envelope.payload["safety"] = veredicto.action.value
        return TutorResponse(content=texto, envelope=envelope)

    async def answer(
        self,
        document_id: Optional[UUID],
        question: str,
        student_id: UUID,
        history: tuple = (),
    ) -> TutorResponse:
        """Devuelve la respuesta del tutor con su envelope de UI.

        Con document_id y ownership → motor pedagógico completo (decisión + emoción).
        Sin documento → modo libre (LlmGate, envelope genérico).
        """
        cuidado = await self._respuesta_de_seguridad(question, document_id)
        if cuidado is not None:
            return cuidado
        intention = self._intent.detect(question)
        profile = None
        if self._profile_repo is not None:
            profile = await self._profile_repo.find_by_student(student_id)

        # Una pregunta sobre el tutor no es una duda del material: sin este
        # desvío recibía una clase y movía la sesión de tutoría.
        eleccion = await self._eleccion_de_estilo(intention, question, history, student_id)
        # Hablar del tutor o de cómo aprende no es una duda del material.
        meta = intention.intent in (TutorIntent.ABOUT, TutorIntent.LEARNING_STYLE) or eleccion[0]
        if document_id is not None and not meta:
            if self._analyze_service is None:
                raise ValueError("Servicio de análisis no configurado para chats con documento")
            plan = await self._analyze_service.prepare_pedagogy(
                document_id,
                question,
                student_id,
                history=history,
                quiz_request=_cuestionario_pedido(intention),
            )
            content = await self._analyze_service.answer_from_plan(plan)
            decision = plan.decision
            milestone = _milestone(profile, decision)
            await self._analyze_service.finalize_interaction(
                plan, content, celebrated_concept=milestone
            )
            affect = self._affect.select(
                profile,
                decision,
                last_score_ratio=_last_graded_ratio(profile, document_id, decision),
            )
            extra = {
                **_intent_payload(intention),
                # La tutoría adaptativa exige material: con documento el turno
                # pasa por el motor; sin él es conversación y no promete más.
                # La UI necesita poder decirlo en vez de aparentar tutoría.
                "grounded": True,
                **_control_flow_payload(plan.adaptation),
            }
            if milestone:
                extra["celebrated_concept"] = milestone
            if plan.explanation:
                extra["explanation"] = plan.explanation
            envelope = ResponseEnvelope.from_decision(
                decision,
                _envelope_type(decision, milestone),
                affect,
                content=content,
                extra=extra,
            )
            return TutorResponse(content=content, envelope=envelope)

        if self._llm_gate is None:
            raise ValueError("LLM gate no configurado para chats libres")
        learner = await self._learner(profile, intention, question, eleccion)
        content = await self._llm_gate.answer_question(
            context="",
            question=question,
            decision=None,
            learning_topic=_tema_a_ofrecer(intention),
            history=history,
            quiz_request=_cuestionario_pedido(intention),
            learner=learner,
        )
        affect = self._affect.select(profile, None)
        envelope = ResponseEnvelope.from_decision(
            None,
            "answer",
            affect,
            content=content,
            extra=_nivel_conocido(
                {**_intent_payload(intention), "grounded": False, **_estilo_elegido(eleccion)},
                learner,
            ),
        )
        return TutorResponse(content=content, envelope=envelope)

    async def answer_stream(
        self,
        document_id: Optional[UUID],
        question: str,
        student_id: UUID,
        history: tuple = (),
    ):
        """Streaming de la respuesta del tutor (yield de trozos).

        Con documento → mismo plan pedagógico que el path no-streaming: la
        decisión y la adaptación prompt-shaping se fijan antes de abrir el
        stream (ADR-004, Decisión 3). Sin documento → modo libre.
        """
        if self._llm_gate is None:
            raise ValueError("LLM gate no configurado para streaming")
        cuidado = await self._respuesta_de_seguridad(question, document_id)
        if cuidado is not None:
            yield cuidado.content, None
            yield cuidado.content, cuidado.envelope
            return
        intention = self._intent.detect(question)
        extra: dict = {
            **_intent_payload(intention),
            "grounded": document_id is not None,
        }
        profile = None
        if self._profile_repo is not None:
            profile = await self._profile_repo.find_by_student(student_id)

        # Una pregunta sobre el tutor no es una duda del material: sin este
        # desvío recibía una clase y movía la sesión de tutoría.
        eleccion = await self._eleccion_de_estilo(intention, question, history, student_id)
        # Hablar del tutor o de cómo aprende no es una duda del material.
        meta = intention.intent in (TutorIntent.ABOUT, TutorIntent.LEARNING_STYLE) or eleccion[0]
        if document_id is not None and not meta:
            if self._analyze_service is None:
                raise ValueError("Servicio de análisis no configurado para chats con documento")
            plan = await self._analyze_service.prepare_pedagogy(
                document_id,
                question,
                student_id,
                history=history,
                quiz_request=_cuestionario_pedido(intention),
            )
            content = ""
            async for token in self._analyze_service.stream_from_plan(plan):
                content += token
                yield token, None
            milestone = _milestone(profile, plan.decision)
            await self._analyze_service.finalize_interaction(
                plan, content, celebrated_concept=milestone
            )

            extra.update(_control_flow_payload(plan.adaptation))
            if milestone:
                extra["celebrated_concept"] = milestone
            if plan.explanation:
                extra["explanation"] = plan.explanation
            envelope = ResponseEnvelope.from_decision(
                plan.decision,
                _envelope_type(plan.decision, milestone),
                self._affect.select(
                    profile,
                    plan.decision,
                    last_score_ratio=_last_graded_ratio(
                        profile, document_id, plan.decision
                    ),
                ),
                content=content,
                extra=extra,
            )
            yield content, envelope
            return

        learner = await self._learner(profile, intention, question, eleccion)
        extra = _nivel_conocido({**extra, **_estilo_elegido(eleccion)}, learner)
        content = ""
        async for token in self._llm_gate.answer_question_stream(
            context="",
            question=question,
            decision=None,
            learning_topic=_tema_a_ofrecer(intention),
            history=history,
            quiz_request=_cuestionario_pedido(intention),
            learner=learner,
        ):
            content += token
            yield token, None

        # Envelope final (tras el streaming) para que el cliente cierre.
        envelope = ResponseEnvelope.from_decision(
            None,
            "answer",
            self._affect.select(profile, None),
            content=content,
            extra=extra,
        )
        yield content, envelope
