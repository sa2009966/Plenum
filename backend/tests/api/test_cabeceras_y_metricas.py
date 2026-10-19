"""Cabeceras de seguridad y /metrics protegido."""
import pytest
from fastapi.testclient import TestClient

from src.infrastructure.config import settings
from src.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_las_respuestas_llevan_cabeceras_de_seguridad(client):
    r = client.get("/health")

    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "max-age" in r.headers["strict-transport-security"]
    assert r.headers["referrer-policy"] == "no-referrer"


def test_con_token_metrics_exige_el_token(client, monkeypatch):
    monkeypatch.setattr(settings, "METRICS_TOKEN", "t" * 32)

    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer malo"}).status_code == 401
    assert client.get("/metrics", headers={"Authorization": f"Bearer {'t' * 32}"}).status_code == 200


def test_el_render_yaml_no_expone_swagger_ni_metricas():
    import pathlib

    y = (pathlib.Path(__file__).parents[3] / "render.yaml").read_text()
    assert 'key: ENABLE_DOCS\n        value: "false"' in y
    assert "key: METRICS_TOKEN" in y


def test_ready_dice_si_esta_listo_pero_el_detalle_solo_con_token(client, monkeypatch):
    """ADR-050: qué dependencia falla y con qué excepción es un mapa de la infraestructura."""
    monkeypatch.setattr(settings, "METRICS_TOKEN", "t" * 32)

    publico = client.get("/ready")
    assert publico.status_code == 200 and publico.json()["status"] == "ready"
    assert "checks" not in publico.json()
    con_token = client.get("/ready", headers={"Authorization": f"Bearer {'t' * 32}"})
    assert con_token.json()["checks"]["app"] == "ok"


def test_cors_admite_el_frontend_sin_credenciales(client):
    """ADR-050: la sesión va en Authorization, no en cookies; credenciales no hacen falta."""
    origen = settings.CORS_ORIGINS[0]
    r = client.options(
        "/api/v1/chats/",
        headers={"Origin": origen, "Access-Control-Request-Method": "POST",
                 "Access-Control-Request-Headers": "authorization"},
    )

    assert r.headers.get("access-control-allow-origin") == origen
    assert "access-control-allow-credentials" not in r.headers
    assert client.options(
        "/api/v1/chats/",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    ).headers.get("access-control-allow-origin") is None
