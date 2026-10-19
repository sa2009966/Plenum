"""Sesiones de Clerk (ADR-027): verificar su token y pedir datos del usuario.

Verificación sin red en cada petición: JWKS en caché, RS256, `iss` de la
instancia, `exp`/`nbf` con margen y `azp` obligatorio y dentro de los orígenes
del frontend (ADR-050).
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

import httpx
import jwt
from jwt import PyJWKClient

CLERK_API = "https://api.clerk.com/v1"


class InvalidClerkToken(ValueError):
    pass


@dataclass(frozen=True)
class ClerkSession:
    user_id: str
    session_id: str | None
    #: Minutos desde que verificó su primer factor (claim `fva[0]`); -1 si no se sabe.
    first_factor_age_min: int


@dataclass(frozen=True)
class ClerkUser:
    user_id: str
    email: str
    email_verified: bool
    username: str


class ClerkSessionVerifier:
    def __init__(
        self,
        issuer: str,
        allowed_origins: list[str],
        origin_regex: str = "",
        jwks_client: PyJWKClient | None = None,
    ) -> None:
        self.issuer = issuer.rstrip("/")
        self._origenes = {o.rstrip("/") for o in allowed_origins}
        self._regex = re.compile(origin_regex) if origin_regex else None
        self._jwks = jwks_client or PyJWKClient(f"{self.issuer}/.well-known/jwks.json", cache_keys=True, lifespan=3600)

    def issued_by_clerk(self, token: str) -> bool:
        """Solo para enrutar (propio o Clerk). NO verifica nada."""
        try:
            return jwt.decode(token, options={"verify_signature": False}).get("iss", "").rstrip("/") == self.issuer
        except jwt.PyJWTError:
            return False

    async def verify(self, token: str) -> ClerkSession:
        return await asyncio.to_thread(self._verify_sync, token)

    def _verify_sync(self, token: str) -> ClerkSession:
        try:
            clave = self._jwks.get_signing_key_from_jwt(token).key
            c = jwt.decode(
                token,
                clave,
                algorithms=["RS256"],
                issuer=self.issuer,
                options={"require": ["exp", "iat", "iss", "sub"], "verify_aud": False},
                leeway=30,
            )
        except (jwt.PyJWTError, ValueError) as exc:
            raise InvalidClerkToken("Sesión no válida.") from exc
        azp = (c.get("azp") or "").rstrip("/")
        # Un token emitido para otro sitio no vale aquí (CSRF, según Clerk). Sin
        # `azp` tampoco (ADR-050): el navegador siempre manda Origin al pedirlo,
        # así que uno sin él salió de fuera del frontend y no hay a quién atribuirlo.
        if not azp or (azp not in self._origenes and not (self._regex and self._regex.match(azp))):
            raise InvalidClerkToken("Sesión no válida.")
        fva = c.get("fva") or [-1]
        return ClerkSession(
            user_id=str(c["sub"]),
            session_id=c.get("sid"),
            first_factor_age_min=int(fva[0]) if fva and fva[0] is not None else -1,
        )


class ClerkBackendClient:
    """Backend API de Clerk con la clave secreta. Solo se usa al vincular y al borrar."""

    def __init__(self, secret_key: str, client: httpx.AsyncClient | None = None) -> None:
        self._headers = {"Authorization": f"Bearer {secret_key}"}
        self._client = client

    async def _request(self, method: str, path: str) -> httpx.Response:
        if self._client is not None:
            return await self._client.request(method, f"{CLERK_API}{path}", headers=self._headers)
        async with httpx.AsyncClient(timeout=15.0) as c:
            return await c.request(method, f"{CLERK_API}{path}", headers=self._headers)

    async def get_user(self, user_id: str) -> ClerkUser:
        r = await self._request("GET", f"/users/{user_id}")
        r.raise_for_status()
        d = r.json()
        primario = d.get("primary_email_address_id")
        correo = next((e for e in d.get("email_addresses") or [] if e.get("id") == primario), None) or {}
        verificado = (correo.get("verification") or {}).get("status") == "verified"
        nombre = d.get("username") or " ".join(x for x in (d.get("first_name"), d.get("last_name")) if x) or ""
        return ClerkUser(
            user_id=user_id,
            email=(correo.get("email_address") or "").strip().lower(),
            email_verified=verificado,
            username=nombre.strip(),
        )

    async def delete_user(self, user_id: str) -> None:
        r = await self._request("DELETE", f"/users/{user_id}")
        if r.status_code not in (200, 404):  # 404: ya no existía, el resultado es el mismo
            r.raise_for_status()


_verificador: ClerkSessionVerifier | None = None
_verificador_para: tuple | None = None


def session_verifier_from_settings() -> ClerkSessionVerifier | None:
    """Verificador según la configuración actual; None si Clerk está apagado."""
    global _verificador, _verificador_para
    from src.infrastructure.config import clerk_enabled, clerk_issuer, settings

    if not clerk_enabled():
        return None
    clave = (clerk_issuer(), tuple(settings.CORS_ORIGINS), settings.CORS_ORIGIN_REGEX or "")
    if _verificador is None or _verificador_para != clave:
        _verificador = ClerkSessionVerifier(clave[0], list(clave[1]), clave[2].strip())
        _verificador_para = clave
    return _verificador
