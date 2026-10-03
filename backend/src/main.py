from contextlib import asynccontextmanager
import asyncio
import logging
import uuid

from fastapi import FastAPI, Request, status
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.infrastructure.config import (
    settings,
    validate_ia_settings,
    validate_runtime_settings,
    validate_security_settings,
)
from src.infrastructure.logging_setup import configure_logging
from src.infrastructure.rate_limit import RateLimitMiddleware
from src.infrastructure.compression import SelectiveGZipMiddleware
from src.infrastructure.security_headers import SecurityHeadersMiddleware
from src.infrastructure.request_logging import RequestLoggingMiddleware
from src.interfaces.api.routers import auth, chats, documents, learning, legal, quizzes, speech, users
from src.interfaces.schemas.http_errors import HTTPErrorBody
from src.domain.services.content_safety import UnsafeTopicError

configure_logging(level=settings.LOG_LEVEL, fmt=settings.LOG_FORMAT)
validate_security_settings(settings)
validate_ia_settings(settings)
validate_runtime_settings(settings)

_logger = logging.getLogger("laria.http")
_INTERNAL_ERROR_DETAIL = "Error interno del servidor."


async def _bootstrap_admin() -> None:
    """Crea el usuario administrador inicial si ADMIN_EMAIL y ADMIN_PASSWORD están definidos."""
    if not settings.ADMIN_EMAIL or not settings.ADMIN_PASSWORD:
        return

    from src.domain.aggregates.user_aggregate import UserAggregate, UserRole
    from src.domain.value_objects.email import Email
    from src.interfaces.api.dependencies import get_user_repo

    repo = get_user_repo()
    existing = await repo.find_by_email(Email(settings.ADMIN_EMAIL))
    if existing is not None:
        return

    try:
        admin = UserAggregate.register(settings.ADMIN_USERNAME, settings.ADMIN_EMAIL, settings.ADMIN_PASSWORD)
    except ValueError as exc:
        raise RuntimeError(f"No se pudo crear el admin inicial (revisa ADMIN_EMAIL/ADMIN_PASSWORD): {exc}") from exc
    admin.change_role(UserRole.ADMIN)
    admin.clear_events()
    await repo.save(admin)


async def _register_learning_projector() -> None:
    from src.application.services.learning_evidence_projector import LearningEvidenceProjector
    from src.interfaces.api.dependencies import (
        get_attempt_repo,
        get_event_bus,
        get_interaction_repo,
        get_metrics,
        get_profile_repo,
        get_quiz_repo,
    )

    projector = LearningEvidenceProjector(
        get_interaction_repo(),
        get_event_bus(),
        profile_repository=get_profile_repo(),
        quiz_repository=get_quiz_repo(),
        attempt_repository=get_attempt_repo(),
        metrics=get_metrics() if settings.METRICS_ENABLED else None,
    )
    await projector.register()


async def _warm_embodiment_stubs() -> None:
    """Carga stubs de embodiment si el flag está activo; no afecta pedagogía."""
    if not settings.EMBODIMENT_ENABLED:
        return
    from src.interfaces.api.dependencies import (
        get_affect_policy,
        get_presence,
        get_speech_to_text,
        get_text_to_speech,
    )

    get_speech_to_text()
    get_text_to_speech()
    get_presence()
    get_affect_policy()
    from src.interfaces.api.dependencies import get_device_command, get_sensor_input

    get_device_command()
    get_sensor_input()


async def _ensure_mongo_indexes(attempts: int = 3, delay_seconds: float = 2.0) -> None:
    """Crea los índices al arrancar, con reintentos y sin tumbar el proceso.

    Un blip de red con Atlas al arrancar no puede dejar el servicio sin nacer:
    antes, cualquier excepción aquí rompía el `lifespan` y Render entraba en
    bucle de reinicio. Si tras los reintentos sigue fallando, el servicio
    arranca degradado y `/ready` lo reporta con 503, que es su trabajo.
    """
    if settings.DB_PROVIDER != "mongodb":
        return
    from src.infrastructure.mongodb.indexes import ensure_all_indexes

    for attempt in range(1, max(1, attempts) + 1):
        try:
            await ensure_all_indexes()
            if attempt > 1:
                _logger.info("mongo_indexes_ready attempt=%d", attempt)
            return
        except Exception:  # noqa: BLE001
            if attempt >= attempts:
                _logger.exception("mongo_indexes_failed attempts=%d", attempts)
                return
            await asyncio.sleep(delay_seconds)


async def _outbox_worker_loop(stop: asyncio.Event) -> None:
    import logging

    from src.infrastructure.mongodb.outbox_event_bus import MongoOutboxEventBus
    from src.interfaces.api.dependencies import get_event_bus, get_metrics

    logger = logging.getLogger("laria.outbox")
    bus = get_event_bus()
    if not isinstance(bus, MongoOutboxEventBus):
        return
    metrics = get_metrics() if settings.METRICS_ENABLED else None
    while not stop.is_set():
        try:
            await bus.process_pending(limit=25)
        except Exception:
            logger.exception("outbox_worker_loop_error")
            if metrics:
                metrics.incr("outbox_failed", reason="worker_loop")
        try:
            await asyncio.wait_for(stop.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            continue


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _ensure_mongo_indexes()
    await _bootstrap_admin()
    await _register_learning_projector()
    await _warm_embodiment_stubs()
    stop = asyncio.Event()
    worker: asyncio.Task | None = None
    if (
        settings.DB_PROVIDER == "mongodb"
        and (settings.EVENT_BUS_BACKEND or "").lower().strip() == "outbox"
    ):
        worker = asyncio.create_task(_outbox_worker_loop(stop))
    yield
    stop.set()
    if worker is not None:
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass
    from src.interfaces.api.dependencies import get_ia_analyst

    analyst = get_ia_analyst()
    if hasattr(analyst, "aclose"):
        await analyst.aclose()
    if settings.DB_PROVIDER == "mongodb":
        from src.infrastructure.mongodb.database import close_database
        await close_database()


_docs = "/docs" if settings.ENABLE_DOCS else None
_redoc = "/redoc" if settings.ENABLE_DOCS else None
_openapi = "/openapi.json" if settings.ENABLE_DOCS else None

app = FastAPI(
    title=settings.APP_TITLE,
    version=settings.APP_VERSION,
    # Nunca exponer tracebacks de FastAPI debug al cliente.
    debug=False,
    docs_url=_docs,
    redoc_url=_redoc,
    openapi_url=_openapi,
    lifespan=lifespan,
)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(SelectiveGZipMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    # Vistas previas de Vercel de los PRs; validado al arrancar.
    allow_origin_regex=(settings.CORS_ORIGIN_REGEX or "").strip() or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(UnsafeTopicError)
async def unsafe_topic_handler(request: Request, exc: UnsafeTopicError):
    """Tema que no se trabaja (ADR-036): 422 con el mensaje y un `reason` estable.

    El cliente lo distingue así de un 422 de validación (que sí tiene arreglo
    reintentando): ante `unsafe_topic` ofrece elegir otro tema, no reintentar.
    """
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "detail": str(exc),
            "reason": "unsafe_topic",
            "safety": exc.verdict.action.value,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """500 controlado para Exception genérica. No convierte HTTPException/422 en 500.

    Starlette registra el handler de `Exception` en ServerErrorMiddleware (fuera de
    RequestLoggingMiddleware); por eso fijamos X-Request-Id aquí si falta.
    """
    if isinstance(exc, StarletteHTTPException):
        return await http_exception_handler(request, exc)
    if isinstance(exc, RequestValidationError):
        return await request_validation_exception_handler(request, exc)

    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    _logger.exception(
        "unhandled_exception method=%s path=%s request_id=%s exc_type=%s",
        request.method,
        request.url.path,
        request_id,
        type(exc).__name__,
    )
    body = HTTPErrorBody(detail=_INTERNAL_ERROR_DETAIL)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=body.model_dump(),
        headers={"X-Request-Id": request_id},
    )


PREFIX = "/api/v1"

app.include_router(auth.router, prefix=PREFIX)
app.include_router(users.router, prefix=PREFIX)
app.include_router(speech.router, prefix=PREFIX)
app.include_router(documents.router, prefix=PREFIX)
app.include_router(quizzes.router, prefix=PREFIX)
app.include_router(learning.router, prefix=PREFIX)
app.include_router(chats.router, prefix=PREFIX)
app.include_router(legal.router, prefix=PREFIX)


def _docs_protegidos(request: Request) -> None:
    """Swagger en producción: detrás de usuario y contraseña (Basic), no público (ADR-024).

    El navegador pide las credenciales solo; un 401 sin la cabecera
    WWW-Authenticate no mostraría el diálogo.
    """
    import base64
    import hmac

    from fastapi import HTTPException

    esperado = f"laria:{settings.DOCS_PASSWORD}".encode()
    dado = request.headers.get("authorization") or ""
    ok = False
    if dado.lower().startswith("basic "):
        try:
            ok = hmac.compare_digest(base64.b64decode(dado[6:].strip()), esperado)
        except Exception:  # noqa: BLE001 — cabecera mal formada
            ok = False
    if not ok:
        raise HTTPException(
            status_code=401,
            detail="Documentación protegida.",
            headers={"WWW-Authenticate": 'Basic realm="Plenum API docs"'},
        )


if not settings.ENABLE_DOCS and settings.DOCS_PASSWORD.strip():
    from fastapi import Depends
    from fastapi.openapi.docs import get_swagger_ui_html

    @app.get("/docs", include_in_schema=False, dependencies=[Depends(_docs_protegidos)])
    def docs_protegidos():
        return get_swagger_ui_html(openapi_url="/openapi.json", title=f"{settings.APP_TITLE} – docs")

    @app.get("/openapi.json", include_in_schema=False, dependencies=[Depends(_docs_protegidos)])
    def openapi_protegido():
        return JSONResponse(app.openapi())


@app.get("/", include_in_schema=False)
def root():
    if settings.ENABLE_DOCS:
        return RedirectResponse(url="/docs")
    return JSONResponse({"service": "LARIA", "health": "/health", "version": settings.APP_VERSION})


@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok", "version": settings.APP_VERSION}


@app.get("/ready", tags=["Health"])
async def readiness_check():
    """Readiness: dependencias opcionales según DB/Redis configurados. No sustituye /health."""
    checks: dict[str, str] = {"app": "ok"}
    ready = True
    if settings.DB_PROVIDER == "mongodb":
        try:
            from src.infrastructure.mongodb.database import get_database

            db = await get_database()
            await db.command("ping")
            checks["mongodb"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["mongodb"] = f"error:{type(exc).__name__}"
            ready = False
    else:
        checks["mongodb"] = "skipped"
    redis_needed = (
        (settings.RATE_LIMIT_BACKEND or "").lower() == "redis"
        or (settings.CACHE_BACKEND or "").lower() == "redis"
    )
    if redis_needed:
        client = None
        try:
            from redis.asyncio import Redis

            client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
            await client.ping()
            checks["redis"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["redis"] = f"error:{type(exc).__name__}"
            ready = False
        finally:
            if client is not None:
                await client.aclose()
    else:
        checks["redis"] = "skipped"

    # Almacén de archivos originales: sin él, subir material falla. Se reporta
    # siempre para que el despliegue sea verificable desde fuera.
    almacen = (settings.ORIGINAL_STORAGE or "blob").lower().strip()
    if almacen == "r2":
        try:
            from src.interfaces.api.dependencies import get_original_blob_store

            await get_original_blob_store().ping()
            checks["storage"] = "r2:ok"
        except Exception as exc:  # noqa: BLE001
            checks["storage"] = f"r2:error:{type(exc).__name__}"
            ready = False
    else:
        checks["storage"] = "blob"

    status = "ready" if ready else "degraded"
    code = 200 if ready else 503
    return JSONResponse(
        {"status": status, "version": settings.APP_VERSION, "checks": checks},
        status_code=code,
    )


@app.get(
    "/metrics",
    tags=["Health"],
    summary="Métricas Prometheus",
    description=(
        "Texto Prometheus (`outbox_*`, `profile_updates`, `laria_llm_latency_ms`, …). "
        "Responde **404** si `METRICS_ENABLED=false`."
    ),
    responses={
        200: {"description": "Contadores en formato Prometheus text."},
        404: {"description": "Métricas deshabilitadas (`METRICS_ENABLED=false`)."},
    },
)
def metrics_endpoint(request: Request):
    if not settings.METRICS_ENABLED:
        return JSONResponse({"detail": "metrics disabled"}, status_code=404)
    # Público exponía volumen de uso, latencias y fallos a cualquiera. Con
    # METRICS_TOKEN definido, solo quien lo presente (el scraper).
    esperado = (settings.METRICS_TOKEN or "").strip()
    if esperado:
        import hmac

        dado = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(dado.encode(), esperado.encode()):
            return JSONResponse({"detail": "No autorizado."}, status_code=401)
    from src.interfaces.api.dependencies import get_metrics
    from src.infrastructure.metrics.in_memory_metrics import InMemoryMetrics

    metrics = get_metrics()
    if isinstance(metrics, InMemoryMetrics):
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse(metrics.render_prometheus(), media_type="text/plain; version=0.0.4")
    return metrics.snapshot()
