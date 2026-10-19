"""Verificación del token de sesión de Clerk y derivación del issuer (ADR-027)."""
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from src.infrastructure.config import Settings, clerk_enabled, clerk_issuer
from src.infrastructure.security.clerk import ClerkSessionVerifier, InvalidClerkToken

ISS = "https://glorious-bluejay-3695.clerk.accounts.dev"
CLAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTRA = rsa.generate_private_key(public_exponent=65537, key_size=2048)
REGEX = r"^https://laria-[a-z0-9-]+-x\.vercel\.app$"


class Jwks:
    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=CLAVE.public_key())


def _tok(clave=CLAVE, **c):
    ahora = int(time.time())
    claims = {"iss": ISS, "sub": "user_1", "sid": "sess_1", "iat": ahora, "nbf": ahora - 5,
              "exp": ahora + 60, "azp": "https://laria-frontend.vercel.app", "fva": [3, -1], **c}
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, clave, algorithm="RS256")


def _v():
    return ClerkSessionVerifier(ISS, ["https://laria-frontend.vercel.app", "http://localhost:4321"], REGEX, jwks_client=Jwks())


def test_el_issuer_se_deriva_de_la_clave_publica():
    s = Settings(CLERK_PUBLISHABLE_KEY="pk_test_Z2xvcmlvdXMtYmx1ZWpheS0zNjk1LmNsZXJrLmFjY291bnRzLmRldiQ", _env_file=None)

    assert clerk_issuer(s) == ISS


def test_el_issuer_explicito_manda_y_own_apaga_clerk():
    s = Settings(CLERK_ISSUER="https://otra.clerk.accounts.dev/", AUTH_MODE="own", _env_file=None)

    assert clerk_issuer(s) == "https://otra.clerk.accounts.dev"
    assert clerk_enabled(s) is False
    assert clerk_enabled(Settings(CLERK_ISSUER=ISS, AUTH_MODE="both", _env_file=None)) is True


def test_una_clave_mal_copiada_no_rompe_nada():
    assert clerk_issuer(Settings(CLERK_PUBLISHABLE_KEY="pk_test_%%%", _env_file=None)) == ""


@pytest.mark.asyncio
async def test_un_token_valido_da_la_sesion_con_la_edad_del_factor():
    s = await _v().verify(_tok())

    assert (s.user_id, s.session_id, s.first_factor_age_min) == ("user_1", "sess_1", 3)


@pytest.mark.asyncio
@pytest.mark.parametrize("azp", ["http://localhost:4321", "https://laria-pr-12-x.vercel.app"])
async def test_origenes_permitidos(azp):
    assert (await _v().verify(_tok(azp=azp))).user_id == "user_1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token",
    [
        pytest.param(_tok(azp="https://evil.example"), id="emitido para otro sitio"),
        # Antes se aceptaba (ADR-027); un token sin origen no sale del navegador (ADR-050).
        pytest.param(_tok(azp=None), id="sin azp"),
        pytest.param(_tok(iss="https://otra.clerk.accounts.dev"), id="otra instancia"),
        pytest.param(_tok(exp=int(time.time()) - 120), id="caducado"),
        pytest.param(_tok(clave=OTRA), id="firma ajena"),
        pytest.param("x.y.z", id="basura"),
    ],
)
async def test_lo_invalido_se_rechaza(token):
    with pytest.raises(InvalidClerkToken):
        await _v().verify(token)


def test_enrutar_por_issuer_no_verifica_pero_distingue():
    v = _v()

    assert v.issued_by_clerk(_tok()) is True
    assert v.issued_by_clerk(jwt.encode({"sub": "x"}, "k" * 40, algorithm="HS256")) is False
