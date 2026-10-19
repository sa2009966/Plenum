"""Sesiones de Clerk en la API, en modo transición (AUTH_MODE=both) y final (ADR-027)."""
import time
from types import SimpleNamespace
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from src.infrastructure.config import settings
from src.infrastructure.security.clerk import ClerkSessionVerifier, ClerkUser
from src.interfaces.api import dependencies as deps
from src.main import app
from tests.conftest import clear_dependency_caches

ISS = "https://test-app.clerk.accounts.dev"
CLAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class Jwks:
    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=CLAVE.public_key())


class ClerkFalso:
    def __init__(self):
        self.usuarios: dict[str, ClerkUser] = {}
        self.consultas = 0
        self.caido = False

    async def get_user(self, user_id):
        self.consultas += 1
        if self.caido:
            raise httpx.ConnectError("caído")
        return self.usuarios[user_id]


def _tok(sub, fva=(1, -1)):
    ahora = int(time.time())
    return jwt.encode({"iss": ISS, "sub": sub, "sid": "sess", "iat": ahora, "nbf": ahora, "exp": ahora + 60,
                       "azp": "http://localhost:4321", "fva": list(fva)}, CLAVE, algorithm="RS256")


@pytest.fixture
def entorno(monkeypatch):
    clear_dependency_caches()
    monkeypatch.setattr(settings, "AUTH_MODE", "both")
    monkeypatch.setattr(settings, "CLERK_ISSUER", ISS)
    clerk = ClerkFalso()
    verificador = ClerkSessionVerifier(ISS, ["http://localhost:4321"], jwks_client=Jwks())
    app.dependency_overrides[deps.get_clerk_verifier] = lambda: verificador
    app.dependency_overrides[deps.get_clerk_client] = lambda: clerk
    # get_current_user llama a las funciones directamente, no por Depends.
    monkeypatch.setattr(deps, "get_clerk_verifier", lambda: verificador)
    monkeypatch.setattr(deps, "get_clerk_client", lambda: clerk)
    with TestClient(app) as c:
        yield c, clerk
    app.dependency_overrides.clear()
    clear_dependency_caches()


def _alta(clerk, correo, verificado=True, nombre="Ana"):
    sub = f"user_{uuid4().hex[:10]}"
    clerk.usuarios[sub] = ClerkUser(user_id=sub, email=correo, email_verified=verificado, username=nombre)
    return sub


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def test_un_usuario_nuevo_de_clerk_entra_y_se_crea(entorno):
    c, clerk = entorno
    correo = f"n_{uuid4().hex[:8]}@example.com"
    sub = _alta(clerk, correo)

    me = c.get("/api/v1/users/me", headers=_h(_tok(sub)))

    assert me.status_code == 200, me.text
    j = me.json()
    assert j["email"] == correo and j["auth_provider"] == "clerk"
    assert j["email_verified"] is True and j["has_password"] is False


def test_solo_la_primera_vez_se_consulta_a_clerk(entorno):
    c, clerk = entorno
    sub = _alta(clerk, f"n_{uuid4().hex[:8]}@example.com")

    id1 = c.get("/api/v1/users/me", headers=_h(_tok(sub))).json()["id"]
    id2 = c.get("/api/v1/users/me", headers=_h(_tok(sub))).json()["id"]

    assert id1 == id2 and clerk.consultas == 1


def test_una_cuenta_antigua_se_vincula_y_conserva_sus_chats(entorno):
    c, clerk = entorno
    correo = f"v_{uuid4().hex[:8]}@example.com"
    c.post("/api/v1/auth/register", json={"username": f"v{uuid4().hex[:6]}", "email": correo, "password": "Clave123"})
    viejo = {"Authorization": "Bearer " + c.post("/api/v1/auth/token", data={"username": correo, "password": "Clave123"}).json()["access_token"]}
    id_viejo = c.get("/api/v1/users/me", headers=viejo).json()["id"]
    chat = c.post("/api/v1/chats/", headers=viejo, json={"title": "Mi chat de antes"}).json()["id"]

    sub = _alta(clerk, correo)
    nuevo = _h(_tok(sub))

    assert c.get("/api/v1/users/me", headers=nuevo).json()["id"] == id_viejo
    assert chat in [x["id"] for x in c.get("/api/v1/chats/", headers=nuevo).json()["chats"]]


def test_un_correo_sin_verificar_en_clerk_no_entra(entorno):
    c, clerk = entorno
    sub = _alta(clerk, f"s_{uuid4().hex[:8]}@example.com", verificado=False)

    r = c.get("/api/v1/users/me", headers=_h(_tok(sub)))
    assert r.status_code == 403 and "Verifica tu correo" in r.json()["detail"]


def test_si_clerk_no_responde_al_vincular_es_503(entorno):
    c, clerk = entorno
    sub = _alta(clerk, f"x_{uuid4().hex[:8]}@example.com")
    clerk.caido = True

    assert c.get("/api/v1/users/me", headers=_h(_tok(sub))).status_code == 503


def test_en_transicion_el_jwt_propio_sigue_valiendo_y_en_modo_clerk_no(entorno, monkeypatch):
    c, _ = entorno
    correo = f"p_{uuid4().hex[:8]}@example.com"
    c.post("/api/v1/auth/register", json={"username": f"p{uuid4().hex[:6]}", "email": correo, "password": "Clave123"})
    propio = {"Authorization": "Bearer " + c.post("/api/v1/auth/token", data={"username": correo, "password": "Clave123"}).json()["access_token"]}

    assert c.get("/api/v1/users/me", headers=propio).status_code == 200
    monkeypatch.setattr(settings, "AUTH_MODE", "clerk")
    assert c.get("/api/v1/users/me", headers=propio).status_code == 401


def test_un_token_de_clerk_manipulado_es_401(entorno):
    c, clerk = entorno
    sub = _alta(clerk, f"m_{uuid4().hex[:8]}@example.com")
    t = _tok(sub)
    manipulado = t[:-4] + ("AAAA" if not t.endswith("AAAA") else "BBBB")

    assert c.get("/api/v1/users/me", headers=_h(manipulado)).status_code == 401


@pytest.mark.asyncio
async def test_el_rate_limit_cuenta_por_usuario_de_clerk(monkeypatch):
    from starlette.requests import Request

    from src.infrastructure import rate_limit as rl
    from src.infrastructure.security import clerk as mod

    verificador = ClerkSessionVerifier(ISS, ["http://localhost:4321"], jwks_client=Jwks())
    monkeypatch.setattr(mod, "session_verifier_from_settings", lambda: verificador)
    req = Request({"type": "http", "method": "POST", "path": "/x", "client": ("10.0.0.1", 1),
                   "headers": [(b"authorization", f"Bearer {_tok('user_42')}".encode())]})

    assert await rl._client_key_async(req) == "c:user_42"


def test_en_modo_clerk_no_se_crean_ni_abren_cuentas_propias(entorno, monkeypatch):
    """ADR-050: con AUTH_MODE=clerk, registro, login y Google propios no existen.

    Antes seguían emitiendo un JWT que ya no abría sesión: rutas públicas sin
    uso que solo servían para crear cuentas y probar contraseñas.
    """
    c, clerk = entorno
    monkeypatch.setattr(settings, "AUTH_MODE", "clerk")

    assert c.post("/api/v1/auth/register", json={"username": "zz", "email": "zz@example.com", "password": "Clave123"}).status_code == 404
    assert c.post("/api/v1/auth/token", data={"username": "zz@example.com", "password": "Clave123"}).status_code == 404
    assert c.post("/api/v1/auth/google", json={"id_token": "x" * 30}).status_code == 404
    # Lo que el frontend necesita para mostrar Clerk sigue ahí, y la sesión de Clerk vale.
    assert c.get("/api/v1/auth/providers").status_code == 200
    sub = _alta(clerk, f"k_{uuid4().hex[:8]}@example.com")
    assert c.get("/api/v1/users/me", headers=_h(_tok(sub))).status_code == 200
