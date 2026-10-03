"""Proveedores de dependencias FastAPI: conectan los adaptadores a los servicios."""
from functools import lru_cache

import httpx
from typing import Annotated, cast
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from src.application.services.analyze_document_service import AnalyzeDocumentService
from src.application.services.document_service import DocumentService
from src.application.services.learning_query_service import LearningQueryService
from src.application.services.llm_gate import LlmGate
from src.application.services.quiz_service import QuizService
from src.application.services.user_service import UserService
from src.domain.aggregates.user_aggregate import UserAggregate
from src.domain.ports.cache_port import CachePort
from src.domain.ports.external_identity import ExternalIdentityVerifier
from src.domain.ports.chat_title_generator import ChatTitleGenerator, ConversationSummarizer
from src.domain.ports.embodiment import (
    DeviceCommandPort,
    PresencePort,
    SensorInputPort,
    SpeechToTextPort,
    TextToSpeechPort,
)
from src.domain.ports.event_bus import EventBus
from src.domain.ports.ia_analyst import IAAnalyst
from src.domain.ports.metrics_port import MetricsPort
from src.domain.ports.document_blob_store import DocumentBlobStore
from src.domain.ports.repositories import (
    ChatRepository,
    ConceptGraphRepository,
    DocumentRepository,
    LearningPathRepository,
    QuizAttemptRepository,
    QuizRepository,
    StudentProfileRepository,
    TutorInteractionRepository,
    TutorSessionRepository,
    UserRepository,
)
from src.domain.services.adaptive_policy import AdaptationCutoffs
from src.domain.services.affect_policy import AffectPolicy
from src.domain.services.model_router import ModelRouter
from src.domain.services.pedagogical_engine import PedagogicalEngine
from src.domain.services.recommendation_engine import RecommendationEngine
from src.infrastructure.config import JWT_ALGORITHM, settings
from src.infrastructure.embodiment.stubs import (
    LogOnlyPresence,
    NullDeviceCommand,
    NullSensorInput,
    NullSpeechToText,
    NullTextToSpeech,
)
from src.infrastructure.openai.openai_ia_analyst import OpenAIAnalyst
from src.infrastructure.persistence import (
    InMemoryChatRepository,
    InMemoryConceptGraphRepository,
    InMemoryDocumentRepository,
    InMemoryEventBus,
    InMemoryLearningPathRepository,
    InMemoryQuizAttemptRepository,
    InMemoryQuizRepository,
    InMemoryStudentProfileRepository,
    InMemoryTutorInteractionRepository,
    InMemoryTutorSessionRepository,
    InMemoryUserRepository,
)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


@lru_cache(maxsize=1)
def get_user_repo() -> UserRepository:
    if settings.DB_PROVIDER == "mongodb":
        from src.infrastructure.mongodb import MongoDBUserRepository
        return MongoDBUserRepository()
    return InMemoryUserRepository()


@lru_cache(maxsize=1)
def get_document_blob_store() -> DocumentBlobStore:
    if settings.DB_PROVIDER == "mongodb":
        from src.infrastructure.mongodb.gridfs_document_blob_store import (
            GridFSDocumentBlobStore,
        )

        return GridFSDocumentBlobStore()
    from src.infrastructure.persistence.in_memory_document_blob_store import (
        InMemoryDocumentBlobStore,
    )

    return InMemoryDocumentBlobStore()


@lru_cache(maxsize=1)
def get_original_blob_store() -> DocumentBlobStore:
    """Dónde se guarda el archivo tal como lo subió el estudiante.

    Por defecto, donde el texto. Con `ORIGINAL_STORAGE=r2` pasa a Cloudflare R2
    sin que el dominio lo note: mismo puerto, otro adaptador (ADR-012).
    """
    if (settings.ORIGINAL_STORAGE or "blob").lower().strip() == "r2":
        from src.infrastructure.storage.r2_document_blob_store import R2DocumentBlobStore

        return R2DocumentBlobStore(
            endpoint_url=settings.R2_ENDPOINT_URL,
            bucket=settings.R2_BUCKET,
            access_key_id=settings.R2_ACCESS_KEY_ID,
            secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            prefix=settings.R2_PREFIX,
        )
    return get_document_blob_store()


@lru_cache(maxsize=1)
def get_document_repo() -> DocumentRepository:
    blob_store = get_document_blob_store()
    if settings.DB_PROVIDER == "mongodb":
        from src.infrastructure.mongodb import MongoDBDocumentRepository

        return MongoDBDocumentRepository(blob_store=blob_store)
    return InMemoryDocumentRepository(blob_store=blob_store)


@lru_cache(maxsize=1)
def get_quiz_repo() -> QuizRepository:
    if settings.DB_PROVIDER == "mongodb":
        from src.infrastructure.mongodb import MongoDBQuizRepository
        return MongoDBQuizRepository()
    return InMemoryQuizRepository()


@lru_cache(maxsize=1)
def get_attempt_repo() -> QuizAttemptRepository:
    if settings.DB_PROVIDER == "mongodb":
        from src.infrastructure.mongodb import MongoDBQuizAttemptRepository
        return MongoDBQuizAttemptRepository()
    return InMemoryQuizAttemptRepository()


@lru_cache(maxsize=1)
def get_interaction_repo() -> TutorInteractionRepository:
    if settings.DB_PROVIDER == "mongodb":
        from src.infrastructure.mongodb import MongoDBTutorInteractionRepository
        return MongoDBTutorInteractionRepository()
    return InMemoryTutorInteractionRepository()


@lru_cache(maxsize=1)
def get_profile_repo() -> StudentProfileRepository:
    if settings.DB_PROVIDER == "mongodb":
        from src.infrastructure.mongodb import MongoDBStudentProfileRepository
        return MongoDBStudentProfileRepository()
    return InMemoryStudentProfileRepository()


@lru_cache(maxsize=1)
def get_concept_graph_repo() -> ConceptGraphRepository:
    if settings.DB_PROVIDER == "mongodb":
        from src.infrastructure.mongodb import MongoDBConceptGraphRepository
        return MongoDBConceptGraphRepository()
    return InMemoryConceptGraphRepository()


@lru_cache(maxsize=1)
def get_session_repo() -> TutorSessionRepository:
    if settings.DB_PROVIDER == "mongodb":
        from src.infrastructure.mongodb import MongoDBTutorSessionRepository
        return MongoDBTutorSessionRepository()
    return InMemoryTutorSessionRepository()


@lru_cache(maxsize=1)
def get_chat_repo() -> ChatRepository:
    if settings.DB_PROVIDER == "mongodb":
        from src.infrastructure.mongodb import MongoDBChatRepository
        return MongoDBChatRepository()
    return InMemoryChatRepository()


@lru_cache(maxsize=1)
def get_study_time_repo():
    if settings.DB_PROVIDER == "mongodb":
        from src.infrastructure.mongodb.study_time_repository import MongoDBStudyTimeRepository

        return MongoDBStudyTimeRepository()
    from src.infrastructure.persistence.in_memory_study_time_repo import InMemoryStudyTimeRepository

    return InMemoryStudyTimeRepository()


def get_study_time_service() -> "StudyTimeService":
    from src.application.services.study_time_service import StudyTimeService

    return StudyTimeService(get_study_time_repo(), get_event_bus(), get_profile_repo())


@lru_cache(maxsize=1)
def get_learning_path_repo() -> LearningPathRepository:
    if settings.DB_PROVIDER == "mongodb":
        from src.infrastructure.mongodb import MongoDBLearningPathRepository
        return MongoDBLearningPathRepository()
    return InMemoryLearningPathRepository()


def get_chat_tutor_service() -> "ChatTutorService":
    from src.application.services.chat_tutor_service import ChatTutorService
    from src.application.services.topic_catalog import TopicCatalog

    return ChatTutorService(
        analyze_service=get_analyze_service(),
        llm_gate=get_llm_gate(),
        document_repository=get_document_repo(),
        profile_repository=get_profile_repo(),
        topic_catalog=TopicCatalog(get_concept_graph_repo()),
        preferences=get_learning_preferences_service(),
        safety=get_content_safety(),
    )


@lru_cache(maxsize=1)
def get_content_safety() -> "ContentSafetyService":
    """Filtro de temas y mensajes (ADR-036). Sin clave o apagado: deja pasar todo."""
    from src.application.services.content_safety_service import ContentSafetyService
    from src.domain.services.content_safety import ContentSafetyPolicy, SafetyThresholds

    moderador = None
    if settings.CONTENT_MODERATION_ENABLED and settings.OPENAI_API_KEY:
        from src.infrastructure.openai.openai_moderator import OpenAIModerator

        moderador = OpenAIModerator(settings.OPENAI_API_KEY)
    umbrales = SafetyThresholds(
        illicit=settings.MODERATION_ILLICIT,
        self_harm=settings.MODERATION_SELF_HARM,
    )
    return ContentSafetyService(moderador, ContentSafetyPolicy(umbrales))


@lru_cache(maxsize=1)
def get_metrics() -> MetricsPort:
    from src.infrastructure.metrics.in_memory_metrics import InMemoryMetrics

    return InMemoryMetrics()


@lru_cache(maxsize=1)
def get_ia_analyst() -> IAAnalyst:
    return OpenAIAnalyst(metrics=get_metrics())


def get_chat_title_generator() -> ChatTitleGenerator:
    return cast(ChatTitleGenerator, get_ia_analyst())


def get_learning_preferences_service() -> "LearningPreferencesService":
    from src.application.services.learning_preferences_service import (
        LearningPreferencesService,
    )

    return LearningPreferencesService(
        event_bus=get_event_bus(), profile_repository=get_profile_repo()
    )


def get_conversation_memory() -> "ConversationMemory":
    from src.application.services.conversation_memory import ConversationMemory

    return ConversationMemory(summarizer=cast(ConversationSummarizer, get_ia_analyst()))


@lru_cache(maxsize=1)
def get_cache() -> CachePort:
    backend = (settings.CACHE_BACKEND or "memory").lower().strip()
    if backend == "redis":
        from src.infrastructure.cache.cache_adapters import RedisCache

        return RedisCache(settings.REDIS_URL)
    from src.infrastructure.cache.cache_adapters import InMemoryCache

    return InMemoryCache()


@lru_cache(maxsize=1)
def get_model_router() -> ModelRouter:
    default = settings.OPENAI_MODEL_DEFAULT or settings.OPENAI_MODEL
    strong = settings.OPENAI_MODEL_STRONG or "gpt-4o"
    return ModelRouter(default_model=default, strong_model=strong)


@lru_cache(maxsize=1)
def get_llm_gate() -> LlmGate:
    return LlmGate(
        ia_analyst=get_ia_analyst(),
        cache=get_cache(),
        model_router=get_model_router(),
        metrics=get_metrics(),
        quiz_repository=get_quiz_repo(),
    )


@lru_cache(maxsize=1)
def get_event_bus() -> EventBus:
    backend = (settings.EVENT_BUS_BACKEND or "memory").lower().strip()
    if backend == "outbox" and settings.DB_PROVIDER == "mongodb":
        from src.infrastructure.mongodb.outbox_event_bus import MongoOutboxEventBus

        return MongoOutboxEventBus(
            metrics=get_metrics() if settings.METRICS_ENABLED else None,
        )
    return InMemoryEventBus()


@lru_cache(maxsize=1)
def get_pedagogical_engine() -> PedagogicalEngine:
    return PedagogicalEngine()


@lru_cache(maxsize=1)
def get_speech_to_text() -> SpeechToTextPort:
    metrics = get_metrics() if settings.METRICS_ENABLED else None
    return NullSpeechToText(metrics=metrics)


@lru_cache(maxsize=1)
def get_text_to_speech() -> TextToSpeechPort:
    if settings.TTS_ENABLED and settings.OPENAI_API_KEY.strip():
        from src.infrastructure.embodiment.openai_tts import OpenAITextToSpeech

        return OpenAITextToSpeech(settings.OPENAI_API_KEY, settings.TTS_MODEL, settings.TTS_VOICE)
    metrics = get_metrics() if settings.METRICS_ENABLED else None
    return NullTextToSpeech(metrics=metrics)


@lru_cache(maxsize=1)
def get_presence() -> PresencePort:
    metrics = get_metrics() if settings.METRICS_ENABLED else None
    return LogOnlyPresence(metrics=metrics)


@lru_cache(maxsize=1)
def get_device_command() -> DeviceCommandPort:
    metrics = get_metrics() if settings.METRICS_ENABLED else None
    return NullDeviceCommand(metrics=metrics)


@lru_cache(maxsize=1)
def get_sensor_input() -> SensorInputPort:
    metrics = get_metrics() if settings.METRICS_ENABLED else None
    return NullSensorInput(metrics=metrics)


@lru_cache(maxsize=1)
def get_affect_policy() -> AffectPolicy:
    return AffectPolicy()


def get_account_service() -> "AccountService":
    from src.application.services.account_service import AccountService

    purgas = []
    if settings.DB_PROVIDER == "mongodb":
        from src.infrastructure.mongodb.outbox_event_bus import purge_personal_events

        purgas.append(purge_personal_events)
    # Tiempo estudiado por día (ADR-033): dato personal, se borra con la cuenta.
    purgas.append(get_study_time_repo().delete_by_student)
    return AccountService(
        user_repository=get_user_repo(),
        document_repository=get_document_repo(),
        document_service=get_document_service(),
        quiz_repository=get_quiz_repo(),
        attempt_repository=get_attempt_repo(),
        interaction_repository=get_interaction_repo(),
        session_repository=get_session_repo(),
        profile_repository=get_profile_repo(),
        chat_repository=get_chat_repo(),
        learning_path_repository=get_learning_path_repo(),
        extra_purges=purgas,
    )


def get_user_service() -> UserService:
    return UserService(get_user_repo(), event_bus=get_event_bus())


def get_document_service() -> DocumentService:
    return DocumentService(
        document_repository=get_document_repo(),
        event_bus=get_event_bus(),
        quiz_repository=get_quiz_repo(),
        attempt_repository=get_attempt_repo(),
        interaction_repository=get_interaction_repo(),
        profile_repository=get_profile_repo(),
        session_repository=get_session_repo(),
        blob_store=get_document_blob_store(),
        original_blob_store=get_original_blob_store(),
        max_upload_bytes=settings.DOCUMENT_MAX_UPLOAD_BYTES,
    )


@lru_cache(maxsize=1)
def get_adaptation_cutoffs() -> AdaptationCutoffs:
    """Los umbrales de la política viven en config, no en ramas del dominio."""
    return AdaptationCutoffs(
        band_low=settings.ADAPT_BAND_LOW,
        band_high=settings.ADAPT_BAND_HIGH,
        abandonment=settings.ADAPT_CUT_ABANDONMENT,
        attention_span=settings.ADAPT_CUT_ATTENTION_SPAN,
        preference=settings.ADAPT_CUT_PREFERENCE,
        ewma_alpha=settings.ADAPT_EWMA_ALPHA,
        long_explanation_chars=settings.ADAPT_LONG_EXPLANATION_CHARS,
        session_gap_minutes=settings.ADAPT_SESSION_GAP_MINUTES,
        min_samples_for_adaptation=settings.ADAPT_MIN_SAMPLES,
    )


def get_analyze_service() -> AnalyzeDocumentService:
    return AnalyzeDocumentService(
        document_repository=get_document_repo(),
        ia_analyst=get_ia_analyst(),
        event_bus=get_event_bus(),
        interaction_repository=get_interaction_repo(),
        profile_repository=get_profile_repo(),
        pedagogical_engine=get_pedagogical_engine(),
        session_repository=get_session_repo(),
        llm_gate=get_llm_gate(),
        metrics=get_metrics() if settings.METRICS_ENABLED else None,
        cutoffs=get_adaptation_cutoffs(),
        adaptation_enabled=not settings.ADAPT_SHADOW_MODE,
        concept_graph_repository=get_concept_graph_repo(),
    )


def get_quiz_service() -> QuizService:
    return QuizService(
        document_repository=get_document_repo(),
        quiz_repository=get_quiz_repo(),
        attempt_repository=get_attempt_repo(),
        interaction_repository=get_interaction_repo(),
        ia_analyst=get_ia_analyst(),
        event_bus=get_event_bus(),
        profile_repository=get_profile_repo(),
        pedagogical_engine=get_pedagogical_engine(),
        session_repository=get_session_repo(),
        llm_gate=get_llm_gate(),
        concept_graph_repository=get_concept_graph_repo(),
        strong_model=settings.OPENAI_MODEL_STRONG,
        analyze_service=get_analyze_service(),
        safety=get_content_safety(),
    )


def get_learning_query_service() -> LearningQueryService:
    return LearningQueryService(
        attempt_repository=get_attempt_repo(),
        interaction_repository=get_interaction_repo(),
        profile_repository=get_profile_repo(),
        recommendation_engine=RecommendationEngine(),
    )


_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="No se pudo validar las credenciales.",
    headers={"WWW-Authenticate": "Bearer"},
)


@lru_cache(maxsize=1)
def get_clerk_verifier():
    """None si Clerk no está activo (AUTH_MODE=own o sin clave pública)."""
    from src.infrastructure.security.clerk import session_verifier_from_settings

    return session_verifier_from_settings()


@lru_cache(maxsize=1)
def get_clerk_client():
    from src.infrastructure.security.clerk import ClerkBackendClient

    return ClerkBackendClient(settings.CLERK_SECRET_KEY.strip())


def _auth_mode() -> str:
    return (settings.AUTH_MODE or "own").strip().lower()


async def _clerk_user(token: str) -> UserAggregate | None:
    """El usuario de un token de Clerk, o None si el token no es de Clerk."""
    verifier = get_clerk_verifier()
    if verifier is None or not verifier.issued_by_clerk(token):
        return None
    from src.infrastructure.security.clerk import InvalidClerkToken

    try:
        sesion = await verifier.verify(token)
    except InvalidClerkToken:
        raise _CREDENTIALS_ERROR
    try:
        return await get_user_service().resolve_clerk_user(sesion.user_id, get_clerk_client())
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except httpx.HTTPError:
        # Clerk no respondió al vincular por primera vez: reintentar es seguro.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No pudimos confirmar tu cuenta ahora mismo. Vuelve a intentarlo.",
        )


async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> UserAggregate:
    """Decodifica el token (propio o de Clerk, ADR-027), carga el usuario y verifica que siga activo."""
    user = await _clerk_user(token)
    if user is not None:
        return _activo(user)
    if _auth_mode() == "clerk":
        # Solo Clerk: el JWT propio ya no abre sesión.
        raise _CREDENTIALS_ERROR
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[JWT_ALGORITHM])
        subject: str | None = payload.get("sub")
        if subject is None:
            raise _CREDENTIALS_ERROR
        user_id = UUID(subject)
    except (jwt.InvalidTokenError, ValueError):
        raise _CREDENTIALS_ERROR

    user = await get_user_repo().find_by_id(user_id)
    if user is None:
        raise _CREDENTIALS_ERROR
    return _activo(user)


def _activo(user: UserAggregate) -> UserAggregate:
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario inactivo.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_current_user_id(user: Annotated[UserAggregate, Depends(get_current_user)]) -> str:
    return str(user.id)


async def require_admin(user: Annotated[UserAggregate, Depends(get_current_user)]) -> UserAggregate:
    if not user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol de administrador.",
        )
    return user


@lru_cache(maxsize=1)
def get_google_verifier() -> "ExternalIdentityVerifier":
    from src.infrastructure.security.google_identity import GoogleIdentityVerifier

    return GoogleIdentityVerifier(settings.GOOGLE_CLIENT_ID)


def get_teaching_service() -> "TeachingService":
    """La clase de una ruta (ADR-028): mismo quiz service, mismo perfil, mismo grafo."""
    from src.application.services.teaching_service import TeachingService
    from src.application.services.topic_catalog import TopicCatalog
    from src.domain.ports.lesson_generator import LessonGenerator

    return TeachingService(
        path_repository=get_learning_path_repo(),
        profile_repository=get_profile_repo(),
        quiz_repository=get_quiz_repo(),
        quiz_service=get_quiz_service(),
        lesson_generator=cast(LessonGenerator, get_ia_analyst()),
        topic_catalog=TopicCatalog(get_concept_graph_repo()),
        attempt_repository=get_attempt_repo(),
        safety=get_content_safety(),
    )
