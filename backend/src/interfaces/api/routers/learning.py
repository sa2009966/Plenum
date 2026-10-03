from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.services.learning_preferences_service import LearningPreferencesService
from src.application.services.learning_query_service import LearningQueryService
from src.application.services.study_time_service import StudyTimeService
from src.application.services.teaching_service import (
    AssessmentRequired,
    NoPendingCheck,
    PathNotFound,
    TeachingService,
)
from src.domain.ports.ia_analyst import IAAnalysisError
from src.domain.services.content_safety import UnsafeTopicError
from src.interfaces.api.quiz_mappers import quiz_to_public_response
from src.domain.aggregates.learning_path import LearningPathAggregate
from src.domain.ports.repositories import (
    LearningPathRepository,
    StudentProfileRepository,
)
from src.interfaces.api.dependencies import (
    get_current_user_id,
    get_learning_path_repo,
    get_learning_preferences_service,
    get_learning_query_service,
    get_profile_repo,
    get_study_time_service,
    get_teaching_service,
)
from src.interfaces.api.openapi_responses import RESP_401_UNAUTHORIZED
from src.interfaces.schemas.learning_path_schemas import (
    CheckAnswerRequest,
    CheckAnswerResponse,
    LearningModuleResponse,
    LearningPathCreateRequest,
    LearningPathListResponse,
    LearningPathResponse,
    LessonResponse,
    NextStepResponse,
    NextTopicItem,
    NextTopicsResponse,
    PathFromTopicRequest,
    StudyDayItem,
    StudyGoals,
    StudyPing,
    StudySummaryResponse,
    TeachingStateResponse,
)
from src.interfaces.schemas.quiz_schemas import (
    ConceptMasteryItem,
    DocumentMasteryItem,
    LearningHistoryResponse,
    LearningPreferences,
    LearningRecommendationItem,
    PedagogicalMemoryItem,
    QuizAttemptSummaryItem,
    StudentProfileResponse,
    TutorInteractionSummaryItem,
)

router = APIRouter(prefix="/learning", tags=["Aprendizaje"])

_MSG_NO_ENCONTRADO = "Ruta de aprendizaje no encontrada"


@router.get(
    "/me",
    response_model=LearningHistoryResponse,
    summary="Historial de evidencia de aprendizaje",
    description=(
        "Devuelve intentos de quiz, interacciones con el tutor y recomendaciones "
        "derivadas del perfil cognitivo (sin auto-declaración)."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
    },
)
async def get_my_learning_history(
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[LearningQueryService, Depends(get_learning_query_service)],
):
    history = await service.get_learning_history(UUID(current_user_id))
    return LearningHistoryResponse(
        attempts=[
            QuizAttemptSummaryItem(
                attempt_id=str(a.attempt_id),
                quiz_id=str(a.quiz_id),
                document_id=str(a.document_id) if a.document_id else None,
                score=a.score,
                total_points=a.total_points,
                completed_at=a.completed_at,
            )
            for a in history.attempts
        ],
        tutor_interactions=[
            TutorInteractionSummaryItem(
                id=str(i.id),
                document_id=str(i.document_id) if i.document_id else None,
                question=i.question,
                answer=i.answer,
                asked_at=i.asked_at,
            )
            for i in history.tutor_interactions
        ],
        recommendations=[
            LearningRecommendationItem(
                kind=r.kind,
                message=r.message,
                document_id=str(r.document_id) if r.document_id else None,
                concept=r.concept,
                priority=r.priority,
                suggested_minutes=r.suggested_minutes,
            )
            for r in history.recommendations
        ],
    )


@router.get(
    "/me/profile",
    response_model=StudentProfileResponse,
    summary="Perfil cognitivo del estudiante",
    description=(
        "Perfil derivado de evidencia multi-señal: mastery efectivo (con olvido), "
        "confianza, memoria pedagógica y ritmo."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
    },
)
async def get_my_profile(
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[LearningQueryService, Depends(get_learning_query_service)],
):
    profile = await service.get_profile(UUID(current_user_id))
    mem = profile.pedagogical_memory
    return StudentProfileResponse(
        student_id=str(profile.student_id),
        pace=profile.pace,
        total_attempts=profile.total_attempts,
        total_struggle_signals=profile.total_struggle_signals,
        frequent_errors=list(profile.frequent_errors),
        updated_at=profile.updated_at,
        learning_velocity=profile.learning_velocity,
        level_by_topic=dict(profile.level_by_topic),
        topic_labels=dict(profile.topic_labels),
        explanation_style_choice=profile.explanation_style_choice,
        pedagogical_memory=(
            PedagogicalMemoryItem(
                frequent_misconceptions=list(mem.frequent_misconceptions),
                successful_examples=list(mem.successful_examples),
                successful_analogies=list(mem.successful_analogies),
                preferred_explanation_style=mem.preferred_explanation_style,
                last_effective_strategies=list(mem.last_effective_strategies),
            )
            if mem
            else None
        ),
        mastery_by_document=[
            DocumentMasteryItem(
                document_id=str(m.document_id),
                attempts=m.attempts,
                mastery=m.mastery,
                last_score_ratio=m.last_score_ratio,
                struggle_signals=m.struggle_signals,
            )
            for m in profile.mastery_by_document
        ],
        mastery_by_concept=[
            ConceptMasteryItem(
                concept_key=c.concept_key,
                attempts=c.attempts,
                mastery=c.mastery,
                last_score_ratio=c.last_score_ratio,
                effective_mastery=c.effective_mastery,
                confidence=c.confidence,
                last_practiced_at=c.last_practiced_at,
                subject=c.subject,
                help_requests=c.help_requests,
                error_streak=c.error_streak,
            )
            for c in profile.mastery_by_concept
        ],
    )


def _map_module(m) -> LearningModuleResponse:
    diff = m.difficulty.value if hasattr(m.difficulty, "value") else str(m.difficulty)
    return LearningModuleResponse(
        id=str(m.id),
        title=m.title,
        concept=m.concept,
        difficulty=diff,
        prerequisites=list(m.prerequisites),
        status=m.status,
        mastery=m.mastery,
        position=m.position,
        kind=m.kind.value if hasattr(m, "kind") else "content",
        tier=m.tier or None,
    )


def _map_teaching(p: LearningPathAggregate) -> TeachingStateResponse | None:
    if not p.topic:
        return None  # ruta creada a mano: sin clase
    t = p.teaching
    actual = p.module(t.concept) if t.concept else None
    vuelta = p.module(t.return_to) if t.return_to else None
    return TeachingStateResponse(
        phase=t.phase.value,
        concept=t.concept,
        concept_title=actual.title if actual else None,
        return_to=t.return_to,
        return_to_title=vuelta.title if vuelta else None,
        variant=t.variant.value,
        pending_check_quiz_id=str(t.pending_check_quiz_id) if t.pending_check_quiz_id else None,
        last_outcome=t.last_outcome.value if t.last_outcome else None,
        passed_concepts=list(t.passed_concepts),
        reason=t.reason,
    )


_DESC_PREFERENCIAS = (
    "Cómo quiere el estudiante que le expliquen. Vale para todos los temas y para los "
    "chats con y sin material. Prioridad: lo que pida en un mensaje concreto > esta "
    "elección > lo que LARIA deduce. `null` = que lo decida LARIA ([ADR-022])."
)


@router.get(
    "/me/preferences",
    response_model=LearningPreferences,
    summary="Mis preferencias de aprendizaje",
    description=_DESC_PREFERENCIAS,
    responses={**RESP_401_UNAUTHORIZED},
)
async def get_my_preferences(
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[LearningPreferencesService, Depends(get_learning_preferences_service)],
):
    return LearningPreferences(
        explanation_style=await service.explanation_style(UUID(current_user_id))
    )


@router.put(
    "/me/preferences",
    response_model=LearningPreferences,
    summary="Elegir cómo quiero que me expliquen",
    description=_DESC_PREFERENCIAS,
    responses={**RESP_401_UNAUTHORIZED},
)
async def put_my_preferences(
    body: LearningPreferences,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[LearningPreferencesService, Depends(get_learning_preferences_service)],
):
    elegido = await service.choose_explanation_style(
        UUID(current_user_id), body.explanation_style
    )
    return LearningPreferences(explanation_style=elegido)


async def _projected(
    path: LearningPathAggregate,
    profile_repo: StudentProfileRepository,
    student_id: UUID,
) -> LearningPathAggregate:
    """Proyecta el mastery del perfil sobre la ruta antes de devolverla.

    El progreso se deriva de la evidencia en cada lectura y no se persiste:
    guardar la proyección volvería a crear dos verdades que hay que mantener
    sincronizadas (ADR-008). La decisión de qué es el mastery sigue estando en
    el dominio; aquí solo se le pasan los números del perfil.
    """
    profile = await profile_repo.find_by_student(student_id)
    if path.topic:
        # Rutas de un tema (ADR-028): lo no medido se da por sabido, no bloquea.
        medidos = (
            {c for c in profile.mastery_by_concept if profile.has_decision_evidence(c)}
            if profile else set()
        )
        path.project_mastery(profile.effective_mastery_by_concept() if profile else {}, measured=medidos)
    else:
        path.project_mastery(profile.effective_mastery_by_concept() if profile else {})
    return path


def _map_path(p: LearningPathAggregate) -> LearningPathResponse:
    return LearningPathResponse(
        id=str(p.id),
        subject=p.subject,
        title=p.title,
        modules=[_map_module(m) for m in p.modules],
        progress=p.progress,
        created_at=p.created_at,
        updated_at=p.updated_at,
        topic=p.topic,
        teaching=_map_teaching(p),
        tiers=list(p.tiers),
        next_tier=p.next_tier,
    )


@router.get(
    "/paths",
    response_model=LearningPathListResponse,
    summary="Listar rutas de aprendizaje",
    responses={**RESP_401_UNAUTHORIZED},
)
async def list_learning_paths(
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    repo: Annotated[LearningPathRepository, Depends(get_learning_path_repo)],
    profile_repo: Annotated[StudentProfileRepository, Depends(get_profile_repo)],
):
    owner = UUID(current_user_id)
    paths = await repo.find_by_owner(owner)
    return LearningPathListResponse(
        paths=[_map_path(await _projected(p, profile_repo, owner)) for p in paths]
    )


@router.post(
    "/paths",
    response_model=LearningPathResponse,
    status_code=201,
    summary="Crear ruta de aprendizaje",
    responses={**RESP_401_UNAUTHORIZED},
)
async def create_learning_path(
    body: LearningPathCreateRequest,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    repo: Annotated[LearningPathRepository, Depends(get_learning_path_repo)],
    profile_repo: Annotated[StudentProfileRepository, Depends(get_profile_repo)],
):
    path = LearningPathAggregate.create(
        owner_id=UUID(current_user_id),
        subject=body.subject,
        title=body.title,
        modules=[
            {
                "title": m.title,
                "concept": m.concept,
                "difficulty": m.difficulty,
                "prerequisites": m.prerequisites,
            }
            for m in body.modules
        ],
    )
    await repo.save(path)
    return _map_path(await _projected(path, profile_repo, UUID(current_user_id)))


@router.get(
    "/paths/{path_id}",
    response_model=LearningPathResponse,
    summary="Obtener ruta de aprendizaje",
    responses={**RESP_401_UNAUTHORIZED},
)
async def get_learning_path(
    path_id: UUID,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    repo: Annotated[LearningPathRepository, Depends(get_learning_path_repo)],
    profile_repo: Annotated[StudentProfileRepository, Depends(get_profile_repo)],
):
    owner = UUID(current_user_id)
    path = await repo.find_by_id(path_id)
    if path is None or not path.is_owned_by(owner):
        raise HTTPException(status_code=404, detail=_MSG_NO_ENCONTRADO)
    return _map_path(await _projected(path, profile_repo, owner))


# No hay endpoint para escribir el mastery de un módulo, a propósito: el
# progreso se gana con evidencia (quizzes, tutoría), no se declara por HTTP
# (ADR-008).


@router.delete(
    "/paths/{path_id}",
    status_code=204,
    summary="Eliminar ruta de aprendizaje",
    responses={**RESP_401_UNAUTHORIZED},
)
async def delete_learning_path(
    path_id: UUID,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    repo: Annotated[LearningPathRepository, Depends(get_learning_path_repo)],
):
    path = await repo.find_by_id(path_id)
    if path is None or not path.is_owned_by(UUID(current_user_id)):
        raise HTTPException(status_code=404, detail=_MSG_NO_ENCONTRADO)
    await repo.delete(path_id)


# --- La clase (ADR-028) --------------------------------------------------------------

_DESC_CLASE = (
    "Flujo: nivelación (`/quizzes/diagnostic`) → `POST /learning/paths/from-topic` → "
    "`POST /learning/paths/{id}/lesson` (explicación + ejemplo + comprobación de 2 preguntas) → "
    "`POST /learning/paths/{id}/check` (califica, registra evidencia y decide el siguiente paso) "
    "→ otra vez `/lesson`. Las decisiones son del backend; el estado vive en la ruta."
)


@router.post(
    "/paths/from-topic",
    response_model=LearningPathResponse,
    summary="Ruta de aprendizaje de un tema (tras la nivelación)",
    description=(
        "Crea la ruta del tema desde el grafo curricular (o, si el grafo no lo cubre, desde un "
        "temario validado y congelado). Idempotente: si ya existe, devuelve la misma. "
        "`teaching.phase` = `assessment` mientras el tema no tenga nivelación. " + _DESC_CLASE
    ),
    responses={**RESP_401_UNAUTHORIZED},
)
async def path_from_topic(
    body: PathFromTopicRequest,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[TeachingService, Depends(get_teaching_service)],
):
    usuario = UUID(current_user_id)
    try:
        path = await service.path_for_topic(usuario, body.topic)
    except UnsafeTopicError:
        raise  # 422 con `reason` (ADR-036), en main.py
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _map_path(await service.projected(path, usuario))


@router.post(
    "/paths/{path_id}/lesson",
    response_model=LessonResponse,
    summary="Paso actual de la clase",
    description=(
        "Devuelve la explicación y la comprobación que tocan. Si ya se entregaron y esperan "
        "respuesta, devuelve las MISMAS (recargar no genera otra). 409 si falta la nivelación; "
        "`check: null` si la ruta está completada. " + _DESC_CLASE
    ),
    responses={**RESP_401_UNAUTHORIZED},
)
async def lesson(
    path_id: UUID,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[TeachingService, Depends(get_teaching_service)],
):
    usuario = UUID(current_user_id)
    try:
        paso = await service.lesson(usuario, path_id)
    except PathNotFound:
        raise HTTPException(status_code=404, detail=_MSG_NO_ENCONTRADO)
    except UnsafeTopicError:
        # Ruta creada antes del filtro de temas (ADR-036): no se dan más clases.
        raise
    except AssessmentRequired as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Primero haz la nivelación de «{exc}» para saber por dónde empezar.",
        )
    except IAAnalysisError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    path = await service.projected(paso.path, usuario)
    return LessonResponse(
        path=_map_path(path),
        markdown=path.teaching.lesson_markdown if paso.check else "",
        check=quiz_to_public_response(paso.check) if paso.check else None,
    )


@router.post(
    "/paths/{path_id}/check",
    response_model=CheckAnswerResponse,
    summary="Responder la comprobación de la clase",
    description=(
        "Califica en servidor por el flujo de quizzes (la evidencia llega al perfil como la de "
        "cualquier quiz), decide si entendió, entendió a medias o no, y deja la clase en el "
        "siguiente paso. 409 si esa no es la comprobación pendiente. " + _DESC_CLASE
    ),
    responses={**RESP_401_UNAUTHORIZED},
)
async def answer_check(
    path_id: UUID,
    body: CheckAnswerRequest,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[TeachingService, Depends(get_teaching_service)],
):
    usuario = UUID(current_user_id)
    try:
        respuestas = {int(k): v for k, v in body.answers.items()}
    except ValueError:
        raise HTTPException(status_code=422, detail="Las respuestas van por índice de pregunta.")
    try:
        r = await service.answer_check(usuario, path_id, body.quiz_id, respuestas)
    except PathNotFound:
        raise HTTPException(status_code=404, detail=_MSG_NO_ENCONTRADO)
    except NoPendingCheck:
        raise HTTPException(
            status_code=409,
            detail="Esa comprobación ya no está pendiente. Pide el paso actual de la clase.",
        )
    path = await service.projected(r.path, usuario)
    siguiente = path.module(r.next.concept) if r.next.concept else None
    return CheckAnswerResponse(
        outcome=r.outcome.value,
        score=r.attempt.score,
        total_points=r.attempt.total_points,
        questions=[
            {
                "index": q.index,
                "text": q.text,
                "selected": q.selected,
                "correct_answer": q.correct_answer,
                "is_correct": q.is_correct,
            }
            for q in r.attempt.questions
        ],
        next=NextStepResponse(
            phase=r.next.phase.value,
            concept=r.next.concept,
            concept_title=siguiente.title if siguiente else None,
            variant=r.next.variant.value if r.next.variant else None,
            reason=r.next.reason,
        ),
        path=_map_path(path),
    )


# --- Metas y tiempo de estudio (ADR-033) ---------------------------------------------


def _resumen(r) -> StudySummaryResponse:
    return StudySummaryResponse(
        today_minutes=r.today_minutes,
        daily_goal_minutes=r.daily_goal_minutes,
        session_minutes=r.session_minutes,
        goal_met_today=r.goal_met_today,
        streak_days=r.streak_days,
        last_7_days=[StudyDayItem(date=d.isoformat(), minutes=m) for d, m in r.last_7_days],
    )


@router.get("/me/study-goals", response_model=StudyGoals, summary="Mis metas de estudio")
async def get_study_goals(
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[StudyTimeService, Depends(get_study_time_service)],
):
    sesion, objetivo = await service.goals(UUID(current_user_id))
    return StudyGoals(session_minutes=sesion, daily_goal_minutes=objetivo)


@router.put(
    "/me/study-goals",
    response_model=StudyGoals,
    summary="Elegir duración de sesión y objetivo diario",
    description=(
        "`session_minutes`: 10, 20, 30, 45 o `null` (sin límite); además dimensiona cada "
        "lección. `daily_goal_minutes`: 10, 15, 30, 45, 60 o `null`. Se guardan en el perfil."
    ),
)
async def put_study_goals(
    body: StudyGoals,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[StudyTimeService, Depends(get_study_time_service)],
):
    sesion, objetivo = await service.choose_goals(
        UUID(current_user_id), body.session_minutes, body.daily_goal_minutes
    )
    return StudyGoals(session_minutes=sesion, daily_goal_minutes=objetivo)


@router.post(
    "/me/study-time",
    response_model=StudySummaryResponse,
    summary="Avisar de tiempo de estudio (cada minuto, desde la clase)",
    description=(
        "Lo cuenta el servidor: cada aviso suma como mucho 60 s y nunca más que el tiempo real "
        "desde el aviso anterior (varias pestañas no cuentan doble). Manda la zona horaria IANA "
        "del navegador. Devuelve el resumen del día."
    ),
)
async def post_study_time(
    body: StudyPing,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[StudyTimeService, Depends(get_study_time_service)],
):
    return _resumen(await service.record(UUID(current_user_id), body.seconds, body.timezone))


@router.get("/me/study-time", response_model=StudySummaryResponse, summary="Tiempo estudiado, objetivo y racha")
async def get_study_time(
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[StudyTimeService, Depends(get_study_time_service)],
    tz: Optional[str] = None,
):
    return _resumen(await service.summary(UUID(current_user_id), tz))



@router.get(
    "/paths/{path_id}/next",
    response_model=NextTopicsResponse,
    summary="Cómo seguir después de una ruta",
    description=(
        "Hasta 3 sugerencias (ADR-034): `level_up` (el mismo tema, más arriba), `advance` "
        "(temas del grafo que se construyen sobre este) o `related` (temas que amplían uno que "
        "el grafo no cubre, propuestos una vez por el modelo). `needs_placement` dice si hay que "
        "nivelarse antes. Sin temas ya completados."
    ),
)
async def next_topics(
    path_id: UUID,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[TeachingService, Depends(get_teaching_service)],
):
    try:
        sugerencias = await service.next_suggestions(UUID(current_user_id), path_id)
    except PathNotFound:
        raise HTTPException(status_code=404, detail=_MSG_NO_ENCONTRADO)
    return NextTopicsResponse(
        suggestions=[
            NextTopicItem(topic=s.topic, label=s.label, kind=s.kind, reason=s.reason, needs_placement=s.needs_placement)
            for s in sugerencias
        ]
    )
