"""Cobertura lifespan, outbox worker y helpers de main.py."""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from starlette.requests import Request

#: /ready sin cabeceras: sin METRICS_TOKEN (desarrollo) trae el detalle (ADR-050).
_SIN_CABECERAS = Request({"type": "http", "method": "GET", "path": "/ready", "headers": []})


@pytest.mark.asyncio
async def test_bootstrap_admin_creates_user(monkeypatch):
    from src.infrastructure.config import settings
    from src.main import _bootstrap_admin

    monkeypatch.setattr(settings, "ADMIN_EMAIL", "admin@test.local")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "SecurePass1x!")
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")

    mock_repo = MagicMock()
    mock_repo.find_by_email = AsyncMock(return_value=None)
    mock_repo.save = AsyncMock()

    with patch("src.interfaces.api.dependencies.get_user_repo", return_value=mock_repo):
        await _bootstrap_admin()
    mock_repo.save.assert_awaited_once()


@pytest.mark.asyncio
async def test_bootstrap_admin_skips_when_exists(monkeypatch):
    from src.infrastructure.config import settings
    from src.main import _bootstrap_admin

    monkeypatch.setattr(settings, "ADMIN_EMAIL", "admin@test.local")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "SecurePass1x!")
    mock_repo = MagicMock()
    mock_repo.find_by_email = AsyncMock(return_value=object())
    with patch("src.interfaces.api.dependencies.get_user_repo", return_value=mock_repo):
        await _bootstrap_admin()
    mock_repo.save.assert_not_called()


@pytest.mark.asyncio
async def test_bootstrap_admin_invalid_password_raises(monkeypatch):
    from src.infrastructure.config import settings
    from src.main import _bootstrap_admin

    monkeypatch.setattr(settings, "ADMIN_EMAIL", "admin@test.local")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "short")
    mock_repo = MagicMock()
    mock_repo.find_by_email = AsyncMock(return_value=None)
    with patch("src.interfaces.api.dependencies.get_user_repo", return_value=mock_repo):
        with pytest.raises(RuntimeError, match="admin inicial"):
            await _bootstrap_admin()


@pytest.mark.asyncio
async def test_ensure_mongo_indexes_skipped_for_memory(monkeypatch):
    from src.infrastructure.config import settings
    from src.main import _ensure_mongo_indexes

    monkeypatch.setattr(settings, "DB_PROVIDER", "memory")
    with patch("src.infrastructure.mongodb.indexes.ensure_all_indexes", AsyncMock()) as fn:
        await _ensure_mongo_indexes()
        fn.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_mongo_indexes_runs_for_mongodb(monkeypatch):
    from src.infrastructure.config import settings
    from src.main import _ensure_mongo_indexes

    monkeypatch.setattr(settings, "DB_PROVIDER", "mongodb")
    with patch("src.infrastructure.mongodb.indexes.ensure_all_indexes", AsyncMock()) as fn:
        await _ensure_mongo_indexes()
        fn.assert_awaited_once()


@pytest.mark.asyncio
async def test_warm_embodiment_when_enabled(monkeypatch):
    from src.infrastructure.config import settings
    from src.main import _warm_embodiment_stubs

    monkeypatch.setattr(settings, "EMBODIMENT_ENABLED", True)
    with patch("src.interfaces.api.dependencies.get_speech_to_text") as stt, patch(
        "src.interfaces.api.dependencies.get_text_to_speech"
    ), patch("src.interfaces.api.dependencies.get_presence"), patch(
        "src.interfaces.api.dependencies.get_affect_policy"
    ), patch(
        "src.interfaces.api.dependencies.get_device_command"
    ), patch(
        "src.interfaces.api.dependencies.get_sensor_input"
    ):
        await _warm_embodiment_stubs()
        stt.assert_called_once()


@pytest.mark.asyncio
async def test_outbox_worker_processes_until_stop(monkeypatch):
    from src.infrastructure.config import settings
    from src.infrastructure.mongodb.outbox_event_bus import MongoOutboxEventBus
    from src.main import _outbox_worker_loop

    monkeypatch.setattr(settings, "METRICS_ENABLED", True)
    stop = asyncio.Event()
    bus = MagicMock(spec=MongoOutboxEventBus)
    bus.process_pending = AsyncMock()

    async def _stop_soon():
        await asyncio.sleep(0.05)
        stop.set()

    with patch("src.interfaces.api.dependencies.get_event_bus", return_value=bus), patch(
        "src.interfaces.api.dependencies.get_metrics"
    ):
        task = asyncio.create_task(_outbox_worker_loop(stop))
        await _stop_soon()
        await asyncio.wait_for(task, timeout=2.0)
    assert bus.process_pending.await_count >= 1


@pytest.mark.asyncio
async def test_outbox_worker_ignores_non_outbox_bus():
    from src.main import _outbox_worker_loop

    stop = asyncio.Event()
    with patch("src.interfaces.api.dependencies.get_event_bus", return_value=MagicMock()):
        stop.set()
        await _outbox_worker_loop(stop)


@pytest.mark.asyncio
async def test_register_learning_projector():
    from src.main import _register_learning_projector

    with patch(
        "src.application.services.learning_evidence_projector.LearningEvidenceProjector.register",
        AsyncMock(),
    ):
        await _register_learning_projector()


def test_root_without_docs(monkeypatch):
    from src.infrastructure.config import settings
    from src.main import app

    monkeypatch.setattr(settings, "ENABLE_DOCS", False)
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["service"] == "LARIA"


def test_metrics_endpoint_disabled(monkeypatch):
    from src.infrastructure.config import settings
    from src.main import app

    monkeypatch.setattr(settings, "METRICS_ENABLED", False)
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/metrics").status_code == 404


def test_metrics_endpoint_prometheus(monkeypatch):
    from src.infrastructure.config import settings
    from src.main import app

    monkeypatch.setattr(settings, "METRICS_ENABLED", True)
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_lifespan_shutdown_closes_analyst(monkeypatch):
    from src.infrastructure.config import settings
    from src.main import lifespan, app

    monkeypatch.setattr(settings, "DB_PROVIDER", "memory")
    monkeypatch.setattr(settings, "EVENT_BUS_BACKEND", "memory")
    monkeypatch.setattr(settings, "EMBODIMENT_ENABLED", False)

    mock_analyst = MagicMock()
    mock_analyst.aclose = AsyncMock()
    with patch("src.main._ensure_mongo_indexes", AsyncMock()), patch(
        "src.main._bootstrap_admin", AsyncMock()
    ), patch("src.main._register_learning_projector", AsyncMock()), patch(
        "src.interfaces.api.dependencies.get_ia_analyst", return_value=mock_analyst
    ):
        async with lifespan(app):
            pass
    mock_analyst.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_outbox_worker_records_failure_metrics(monkeypatch):
    from src.infrastructure.config import settings
    from src.infrastructure.mongodb.outbox_event_bus import MongoOutboxEventBus
    from src.main import _outbox_worker_loop

    monkeypatch.setattr(settings, "METRICS_ENABLED", True)
    stop = asyncio.Event()
    bus = MagicMock(spec=MongoOutboxEventBus)
    bus.process_pending = AsyncMock(side_effect=RuntimeError("boom"))
    metrics = MagicMock()

    async def _stop_soon():
        await asyncio.sleep(0.05)
        stop.set()

    with patch("src.interfaces.api.dependencies.get_event_bus", return_value=bus), patch(
        "src.interfaces.api.dependencies.get_metrics", return_value=metrics
    ):
        task = asyncio.create_task(_outbox_worker_loop(stop))
        await _stop_soon()
        await asyncio.wait_for(task, timeout=2.0)
    metrics.incr.assert_any_call("outbox_failed", reason="worker_loop")


@pytest.mark.asyncio
async def test_lifespan_starts_outbox_worker_and_closes_mongo(monkeypatch):
    from src.infrastructure.config import settings
    from src.main import lifespan, app

    monkeypatch.setattr(settings, "DB_PROVIDER", "mongodb")
    monkeypatch.setattr(settings, "EVENT_BUS_BACKEND", "outbox")
    monkeypatch.setattr(settings, "EMBODIMENT_ENABLED", False)

    mock_analyst = MagicMock()
    mock_analyst.aclose = AsyncMock()
    close_db = AsyncMock()
    with patch("src.main._ensure_mongo_indexes", AsyncMock()), patch(
        "src.main._bootstrap_admin", AsyncMock()
    ), patch("src.main._register_learning_projector", AsyncMock()), patch(
        "src.main._outbox_worker_loop", AsyncMock()
    ) as worker_loop, patch(
        "src.interfaces.api.dependencies.get_ia_analyst", return_value=mock_analyst
    ), patch("src.infrastructure.mongodb.database.close_database", close_db):
        async with lifespan(app):
            await asyncio.sleep(0.01)
        worker_loop.assert_called()
    close_db.assert_awaited_once()
    mock_analyst.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_bootstrap_admin_skips_without_credentials(monkeypatch):
    from src.infrastructure.config import settings
    from src.main import _bootstrap_admin

    monkeypatch.setattr(settings, "ADMIN_EMAIL", "")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "")
    with patch("src.interfaces.api.dependencies.get_user_repo") as get_repo:
        await _bootstrap_admin()
        get_repo.assert_not_called()


def test_root_redirects_to_docs_when_enabled(monkeypatch):
    from src.infrastructure.config import settings
    from src.main import app

    monkeypatch.setattr(settings, "ENABLE_DOCS", True)
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/docs"


@pytest.mark.asyncio
async def test_readiness_mongodb_ok_and_redis_skipped(monkeypatch):
    from src.infrastructure.config import settings
    from src.main import readiness_check

    monkeypatch.setattr(settings, "DB_PROVIDER", "mongodb")
    monkeypatch.setattr(settings, "RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setattr(settings, "CACHE_BACKEND", "memory")

    mock_db = MagicMock()
    mock_db.command = AsyncMock(return_value={"ok": 1})
    with patch("src.infrastructure.mongodb.database.get_database", AsyncMock(return_value=mock_db)):
        resp = await readiness_check(_SIN_CABECERAS)
    body = resp.body.decode()
    assert '"mongodb":"ok"' in body
    assert '"redis":"skipped"' in body
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_readiness_mongodb_failure_returns_503(monkeypatch):
    from src.infrastructure.config import settings
    from src.main import readiness_check

    monkeypatch.setattr(settings, "DB_PROVIDER", "mongodb")
    monkeypatch.setattr(settings, "CACHE_BACKEND", "memory")
    monkeypatch.setattr(settings, "RATE_LIMIT_BACKEND", "memory")

    with patch(
        "src.infrastructure.mongodb.database.get_database",
        AsyncMock(side_effect=ConnectionError("down")),
    ):
        resp = await readiness_check(_SIN_CABECERAS)
    assert resp.status_code == 503
    assert "error:ConnectionError" in resp.body.decode()


@pytest.mark.asyncio
async def test_readiness_redis_ok(monkeypatch):
    from src.infrastructure.config import settings
    from src.main import readiness_check

    monkeypatch.setattr(settings, "DB_PROVIDER", "memory")
    monkeypatch.setattr(settings, "RATE_LIMIT_BACKEND", "redis")
    monkeypatch.setattr(settings, "CACHE_BACKEND", "memory")
    monkeypatch.setattr(settings, "REDIS_URL", "redis://localhost:6379/0")

    mock_client = MagicMock()
    mock_client.ping = AsyncMock(return_value=True)
    mock_client.aclose = AsyncMock()
    mock_redis_mod = MagicMock()
    mock_redis_mod.Redis.from_url.return_value = mock_client
    # `redis.asyncio`: el ping síncrono bloqueaba el event loop en /ready.
    with patch.dict("sys.modules", {"redis.asyncio": mock_redis_mod}):
        resp = await readiness_check(_SIN_CABECERAS)
    assert resp.status_code == 200
    assert '"redis":"ok"' in resp.body.decode()
    mock_client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_readiness_redis_failure_returns_503(monkeypatch):
    from src.infrastructure.config import settings
    from src.main import readiness_check

    monkeypatch.setattr(settings, "DB_PROVIDER", "memory")
    monkeypatch.setattr(settings, "CACHE_BACKEND", "redis")
    monkeypatch.setattr(settings, "RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setattr(settings, "REDIS_URL", "redis://localhost:6379/0")

    # Se parchea `redis.asyncio`, que es lo que importa `/ready`. Parchear
    # `redis` a secas hacía que el resultado dependiera de si otro test había
    # importado el submódulo antes: pasaba en la suite y fallaba en aislado.
    mock_redis_mod = MagicMock()
    mock_redis_mod.Redis.from_url.side_effect = ConnectionError("redis down")
    with patch.dict("sys.modules", {"redis.asyncio": mock_redis_mod}):
        resp = await readiness_check(_SIN_CABECERAS)
    assert resp.status_code == 503
    assert "error:ConnectionError" in resp.body.decode()


def test_metrics_endpoint_non_inmemory_snapshot(monkeypatch):
    from src.infrastructure.config import settings
    from src.main import app

    monkeypatch.setattr(settings, "METRICS_ENABLED", True)
    metrics = MagicMock()
    metrics.snapshot.return_value = {"counters": {}}
    with patch("src.interfaces.api.dependencies.get_metrics", return_value=metrics):
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/metrics")
    assert r.status_code == 200
    metrics.snapshot.assert_called_once()


@pytest.mark.asyncio
async def test_outbox_worker_without_metrics(monkeypatch):
    from src.infrastructure.mongodb.outbox_event_bus import MongoOutboxEventBus
    from src.main import _outbox_worker_loop

    monkeypatch.setattr("src.main.settings.METRICS_ENABLED", False)
    stop = asyncio.Event()
    bus = MagicMock(spec=MongoOutboxEventBus)
    bus.process_pending = AsyncMock()

    async def _stop_soon():
        await asyncio.sleep(0.05)
        stop.set()

    with patch("src.interfaces.api.dependencies.get_event_bus", return_value=bus):
        task = asyncio.create_task(_outbox_worker_loop(stop))
        await _stop_soon()
        await asyncio.wait_for(task, timeout=2.0)
    assert bus.process_pending.await_count >= 1


@pytest.mark.asyncio
async def test_lifespan_cancels_outbox_worker(monkeypatch):
    from src.infrastructure.config import settings
    from src.main import lifespan, app

    monkeypatch.setattr(settings, "DB_PROVIDER", "mongodb")
    monkeypatch.setattr(settings, "EVENT_BUS_BACKEND", "outbox")
    monkeypatch.setattr(settings, "EMBODIMENT_ENABLED", False)

    mock_analyst = MagicMock()
    mock_analyst.aclose = AsyncMock()
    with patch("src.main._ensure_mongo_indexes", AsyncMock()), patch(
        "src.main._bootstrap_admin", AsyncMock()
    ), patch("src.main._register_learning_projector", AsyncMock()), patch(
        "src.interfaces.api.dependencies.get_ia_analyst", return_value=mock_analyst
    ), patch("src.infrastructure.mongodb.database.close_database", AsyncMock()):

        async def _hang(stop):
            await stop.wait()

        with patch("src.main._outbox_worker_loop", side_effect=_hang):
            async with lifespan(app):
                pass


@pytest.mark.asyncio
async def test_readiness_reporta_el_almacen_por_defecto(monkeypatch):
    """Sin R2, `/ready` dice `blob` en vez de callar: el despliegue es verificable."""
    from src.infrastructure.config import settings
    from src.main import readiness_check

    monkeypatch.setattr(settings, "DB_PROVIDER", "memory")
    monkeypatch.setattr(settings, "RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setattr(settings, "CACHE_BACKEND", "memory")
    monkeypatch.setattr(settings, "ORIGINAL_STORAGE", "blob")

    resp = await readiness_check(_SIN_CABECERAS)

    assert resp.status_code == 200
    assert '"storage":"blob"' in resp.body.decode()


@pytest.mark.asyncio
async def test_readiness_degrada_si_r2_no_responde(monkeypatch):
    """Si los originales no se pueden guardar, subir material falla: eso es 503."""
    from src.infrastructure.config import settings
    from src.interfaces.api import dependencies as deps
    from src.main import readiness_check

    monkeypatch.setattr(settings, "DB_PROVIDER", "memory")
    monkeypatch.setattr(settings, "RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setattr(settings, "CACHE_BACKEND", "memory")
    monkeypatch.setattr(settings, "ORIGINAL_STORAGE", "r2")

    class AlmacenCaido:
        async def ping(self):
            raise ConnectionError("bucket inalcanzable")

    monkeypatch.setattr(deps, "get_original_blob_store", lambda: AlmacenCaido())

    resp = await readiness_check(_SIN_CABECERAS)

    assert resp.status_code == 503
    assert "r2:error:ConnectionError" in resp.body.decode()
