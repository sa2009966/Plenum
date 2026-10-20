"""Rate limiting por usuario (o IP si no hay sesión) y ruta (memory o Redis).

Por usuario y no por IP: en Render la IP que ve la app es la del balanceador,
la misma para todos. Contar por IP convertía cada límite en uno GLOBAL (10
logins por minuto para toda la plataforma, 8 preguntas al tutor…): un atacante
bloqueaba a todos y una clase registrándose a la vez chocaba con el tope.

El contador es **asíncrono** a propósito: el middleware corre en el event loop y
el backend Redis va por red. Con el cliente síncrono, cada request rate-limitada
bloqueaba el loop entero durante el viaje de ida y vuelta a Redis.
"""
from __future__ import annotations

import ipaddress
import logging
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Protocol

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.infrastructure.config import settings

logger = logging.getLogger("laria.http")


class RateLimitCounter(Protocol):
    async def allow(self, key: str, limit: int, window_seconds: float) -> bool: ...


class SlidingWindowCounter:
    """Ventana deslizante en memoria, por proceso.

    También es el plan B del contador Redis: si el backend compartido falla, el
    borde sigue protegido (peor, por réplica) en vez de caerse.
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    async def allow(self, key: str, limit: int, window_seconds: float) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._hits[key]
            cutoff = now - window_seconds
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            return True


class RedisSlidingWindow:
    """Contador sliding window compartido entre réplicas (Redis sorted set).

    Espera un cliente `redis.asyncio`. Ante fallo de Redis degrada al contador
    local en vez de devolver 500: un limitador caído no puede tumbar el borde.
    """

    def __init__(self, redis_client, fallback: RateLimitCounter | None = None) -> None:
        self._redis = redis_client
        self._fallback = fallback or SlidingWindowCounter()
        self._degraded = False

    async def allow(self, key: str, limit: int, window_seconds: float) -> bool:
        now = time.time()
        cutoff = now - window_seconds
        rkey = f"rl:{key}"
        try:
            pipe = self._redis.pipeline()
            pipe.zremrangebyscore(rkey, 0, cutoff)
            pipe.zcard(rkey)
            pipe.zadd(rkey, {f"{now}": now})
            pipe.expire(rkey, int(window_seconds) + 1)
            results = await pipe.execute()
        except Exception:  # noqa: BLE001 — cualquier fallo de red degrada, no rompe
            if not self._degraded:
                self._degraded = True
                logger.warning("rate_limit_redis_degraded key=%s", key, exc_info=True)
            return await self._fallback.allow(key, limit, window_seconds)
        if self._degraded:
            self._degraded = False
            logger.info("rate_limit_redis_recovered")
        count_before = int(results[1])
        return count_before < limit


# Orden: rutas IA específicas se resuelven en `_match_rule`.
_RULES_DOC = "see _match_rule"

def _match_rule(path: str, method: str) -> tuple[str, int, float] | None:
    # Sin sesión solo hay IP, y la IP puede ser compartida (balanceador): estos
    # topes son holgados y frenan volumen. La fuerza bruta contra una cuenta la
    # frena el límite por correo del propio login (`login_attempt_allowed`).
    if path.startswith("/api/v1/auth/register"):
        return ("/api/v1/auth/register", 30, 60.0)
    if path.startswith("/api/v1/auth/google"):
        return ("/api/v1/auth/google", 30, 60.0)
    if path.startswith("/api/v1/auth/token"):
        return ("/api/v1/auth/token", 60, 60.0)
    # Pide la contraseña: sin límite serviría para adivinarla a fuerza bruta.
    if method == "DELETE" and path.rstrip("/") == "/api/v1/users/me":
        return ("/api/v1/users/me:delete", 5, 60.0)
    if method == "POST" and path.rstrip("/") == "/api/v1/chats/generate-title":
        return ("ia:title", 8, 60.0)
    # La clase genera contenido con el modelo en cada paso (ADR-028).
    if method == "POST" and path.startswith("/api/v1/learning/paths/") and path.endswith("/lesson"):
        return ("ia:lesson", 12, 60.0)
    if method == "POST" and path.rstrip("/") == "/api/v1/learning/paths/from-topic":
        return ("ia:lesson", 12, 60.0)
    # La prueba de paso genera un quiz con el modelo en cada llamada (ADR-042/043).
    if method == "POST" and path.startswith("/api/v1/learning/paths/") and path.endswith("/passage-test"):
        return ("ia:passage", 6, 60.0)
    # Tiempo estudiado: un aviso por minuto; margen para varias pestañas.
    if method == "POST" and path.rstrip("/") == "/api/v1/learning/me/study-time":
        return ("study-time", 10, 60.0)
    # Voz: una petición por frase, así que el tope es más alto que el del chat.
    if method == "POST" and path.rstrip("/") == "/api/v1/speech":
        return ("ia:tts", 60, 60.0)
    # Cada mensaje del chat es una llamada al modelo: sin límite, un solo
    # usuario podía generar gasto ilimitado en OpenAI.
    if method == "POST" and path.startswith("/api/v1/chats/") and (
        path.endswith("/messages") or path.endswith("/stream")
    ):
        return ("ia:chat", 20, 60.0)
    if "/analyze" in path:
        return ("ia:analyze", 8, 60.0)
    if path.rstrip("/").endswith("/ask") or "/ask" in path:
        return ("ia:ask", 8, 60.0)
    if method == "POST" and "/quiz" in path and "/attempts" not in path:
        return ("ia:quiz", 8, 60.0)
    # Enviar un intento o una comprobación puede corregir abiertas con el modelo
    # (ADR-053): una llamada por respuesta abierta.
    if method == "POST" and (
        (path.startswith("/api/v1/quizzes/") and path.rstrip("/").endswith("/attempts"))
        or (path.startswith("/api/v1/learning/paths/") and path.rstrip("/").endswith("/check"))
    ):
        return ("ia:grade", 20, 60.0)
    if path.startswith("/api/v1/documents/"):
        return ("/api/v1/documents/", 30, 60.0)
    if path.startswith("/api/v1/quizzes/"):
        return ("/api/v1/quizzes/", 20, 60.0)
    return None


def _parse_trusted_proxies(raw: str) -> list[ipaddress._BaseNetwork | ipaddress._BaseAddress]:
    out: list = []
    for part in (raw or "").split(","):
        token = part.strip()
        if not token:
            continue
        try:
            if "/" in token:
                out.append(ipaddress.ip_network(token, strict=False))
            else:
                out.append(ipaddress.ip_address(token))
        except ValueError:
            continue
    return out


def _client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    trusted = _parse_trusted_proxies(settings.TRUSTED_PROXIES)
    if not trusted:
        return peer
    try:
        peer_addr = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    peer_ok = False
    for t in trusted:
        if isinstance(t, (ipaddress.IPv4Network, ipaddress.IPv6Network)):
            if peer_addr in t:
                peer_ok = True
                break
        elif peer_addr == t:
            peer_ok = True
            break
    if not peer_ok:
        return peer
    xff = request.headers.get("x-forwarded-for") or ""
    if not xff:
        return peer
    return xff.split(",")[0].strip() or peer


def _client_key(request: Request) -> str:
    """El usuario del token si es válido; si no, la IP.

    El token se VERIFICA: sin firma, un atacante rotaría el `sub` para esquivar
    el límite. Uno inválido cae a la IP y la ruta responderá 401 de todos modos.
    """
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        try:
            import jwt

            from src.infrastructure.config import JWT_ALGORITHM

            payload = jwt.decode(auth[7:].strip(), settings.SECRET_KEY, algorithms=[JWT_ALGORITHM])
            sub = payload.get("sub")
            if sub:
                return f"u:{sub}"
        except Exception:  # noqa: BLE001 — token inválido: se limita por IP
            pass
    return f"ip:{_client_ip(request)}"


async def _client_key_async(request: Request) -> str:
    """Como `_client_key`, pero reconoce también los tokens de Clerk (ADR-027).

    Sin esto, un usuario de Clerk contaría por IP, que en Render es compartida:
    el límite volvería a ser global.
    """
    clave = _client_key(request)
    if not clave.startswith("ip:"):
        return clave
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return clave
    from src.infrastructure.security.clerk import InvalidClerkToken, session_verifier_from_settings

    verificador = session_verifier_from_settings()
    token = auth[7:].strip()
    if verificador is None or not verificador.issued_by_clerk(token):
        return clave
    try:
        return f"c:{(await verificador.verify(token)).user_id}"
    except InvalidClerkToken:
        return clave


_shared_counter: RateLimitCounter | None = None


def shared_rate_limit_counter() -> RateLimitCounter:
    """Un solo contador para el middleware y los límites de dominio (login por correo)."""
    global _shared_counter
    if _shared_counter is None:
        _shared_counter = build_rate_limit_counter()
    return _shared_counter


#: Intentos de login por cuenta: 10 cada 15 minutos. Por correo y no por IP, así
#: que adivinar la contraseña de una cuenta no depende de desde dónde se ataque,
#: y bloquear una cuenta no bloquea a las demás.
LOGIN_ATTEMPTS_PER_ACCOUNT = 10
LOGIN_WINDOW_SECONDS = 900.0


async def login_attempt_allowed(email: str) -> bool:
    if not settings.RATE_LIMIT_ENABLED:
        return True
    clave = f"login:{(email or '').strip().lower()}"
    return await shared_rate_limit_counter().allow(
        clave, LOGIN_ATTEMPTS_PER_ACCOUNT, LOGIN_WINDOW_SECONDS
    )


def build_rate_limit_counter() -> RateLimitCounter:
    backend = (settings.RATE_LIMIT_BACKEND or "memory").lower().strip()
    if backend == "redis":
        # Cliente asíncrono y conexión perezosa: sin `ping()` de arranque, que
        # se pagaba bloqueando el loop en la primera request rate-limitada.
        from redis.asyncio import Redis

        client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        return RedisSlidingWindow(client)
    return SlidingWindowCounter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, counter: RateLimitCounter | None = None) -> None:
        super().__init__(app)
        self._counter = counter

    def _get_counter(self) -> RateLimitCounter:
        if self._counter is None:
            self._counter = shared_rate_limit_counter()
        return self._counter

    async def dispatch(self, request: Request, call_next) -> Response:
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)
        rule = _match_rule(request.url.path, request.method.upper())
        if rule is None:
            return await call_next(request)
        prefix, limit, window = rule
        key = f"{await _client_key_async(request)}:{prefix}"
        if not await self._get_counter().allow(key, limit, window):
            contenido = {"detail": "Demasiadas solicitudes. Intenta de nuevo más tarde."}
            if prefix == "ia:grade":
                # El cliente lo distingue para no perder lo escrito (ADR-053).
                contenido["reason"] = "grade_rate_limited"
            return JSONResponse(status_code=429, content=contenido, headers={"Retry-After": "60"})
        return await call_next(request)
