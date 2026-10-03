from typing import Annotated, Any

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Valores que jamás deben usarse como SECRET_KEY en ejecución real.
_INSECURE_SECRET_KEYS = {"", "cambia-esto-en-produccion", "changeme", "secret"}

# Algoritmo JWT fijo (no configurable por entorno).
JWT_ALGORITHM = "HS256"


def _parse_cors_origins(value: Any) -> list[str]:
    """Acepta JSON array o lista CSV (Render a veces rompe las comillas del JSON)."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip().rstrip("/") for v in value if str(v).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        import json

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            # Fallback: quitar corchetes/comillas rotas y tratar como CSV
            text = text.strip("[]")
        else:
            if isinstance(parsed, list):
                return [str(v).strip().rstrip("/") for v in parsed if str(v).strip()]
            text = str(parsed)
    parts = [p.strip().strip('"').strip("'").rstrip("/") for p in text.split(",")]
    return [p for p in parts if p]


class Settings(BaseSettings):
    """Configuración central cargada desde variables de entorno / .env"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Proveedor de IA: solo "openai" (legacy "kimi" rechazado al arrancar)
    IA_PROVIDER: str = "openai"

    # OpenAI API
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_MODEL_DEFAULT: str = "gpt-4o-mini"
    OPENAI_MODEL_STRONG: str = "gpt-4o"
    #: Filtro de temas y mensajes (ADR-036). Apagarlo es solo para emergencias.
    CONTENT_MODERATION_ENABLED: bool = True
    #: Umbrales de la política (0-1). El resto vive en SafetyThresholds.
    MODERATION_ILLICIT: float = 0.5
    MODERATION_SELF_HARM: float = 0.5

    # Seguridad JWT
    SECRET_KEY: str = ""
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # CORS: JSON array o CSV. NoDecode evita que pydantic-settings falle antes del validador.
    CORS_ORIGINS: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://localhost:4321",
    ]
    # Orígenes por patrón, para las vistas previas de Vercel: cada PR tiene una
    # URL distinta y no caben en una lista. Vacío = desactivado. Tiene que ir
    # anclado (^…$) y no puede dejar pasar orígenes ajenos: se comprueba al
    # arrancar (`validate_security_settings`).
    CORS_ORIGIN_REGEX: str = ""

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _coerce_cors_origins(cls, value: Any) -> list[str]:
        return _parse_cors_origins(value)

    # Admin inicial opcional (se crea al arrancar si ambos están definidos)
    ADMIN_USERNAME: str = "admin"
    ADMIN_EMAIL: str = ""
    ADMIN_PASSWORD: str = ""

    # Base de datos: "memory" o "mongodb"
    DB_PROVIDER: str = "memory"

    # MongoDB
    MONGODB_URL: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "laria_db"
    # Selección de servidor y conexión. 3 s van bien en local; en Atlas conviene
    # subirlo (SRV + TLS + tier compartido en frío).
    MONGODB_TIMEOUT_MS: int = 3_000

    # Upload de materiales (multipart / JSON). 200 MiB por defecto.
    DOCUMENT_MAX_UPLOAD_BYTES: int = 26_214_400  # 25 MiB
    # Dónde vive el archivo original (el texto extraído siempre va al blob de
    # contenido). `blob` = donde el texto (GridFS/memoria); `r2` = Cloudflare R2.
    ORIGINAL_STORAGE: str = "blob"  # blob | r2
    R2_ENDPOINT_URL: str = ""  # https://<account_id>.r2.cloudflarestorage.com
    R2_BUCKET: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_PREFIX: str = "documents/"

    # Redis (rate limit horizontal + caché inteligente)
    REDIS_URL: str = "redis://localhost:6379/0"
    RATE_LIMIT_BACKEND: str = "memory"  # memory | redis
    CACHE_BACKEND: str = "memory"  # memory | redis
    TRUSTED_PROXIES: str = ""  # CSV de IPs/CIDR que pueden fijar X-Forwarded-For

    # Aplicación
    APP_ENV: str = "development"  # development | production
    APP_TITLE: str = "Plenum – API de LARIA, el tutor adaptativo"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    ENABLE_DOCS: bool = False
    RATE_LIMIT_ENABLED: bool = True
    EMBODIMENT_ENABLED: bool = False
    EVENT_BUS_BACKEND: str = "memory"  # memory | outbox
    METRICS_ENABLED: bool = True
    #: Si se define, /metrics exige `Authorization: Bearer <token>`.
    METRICS_TOKEN: str = ""
    #: Con ENABLE_DOCS=false, /docs y /openapi.json siguen disponibles detrás de
    #: usuario ("laria") y esta contraseña. Vacía = documentación apagada del todo.
    DOCS_PASSWORD: str = ""
    #: Client ID de OAuth de Google (público). Vacío = "Continuar con Google" apagado.
    GOOGLE_CLIENT_ID: str = ""
    #: Clerk. La pública la puede leer el cliente; la secreta no sale del proceso.
    #: Vacías = Clerk apagado. Nunca van en git. El nombre NEXT_PUBLIC_ es el del
    #: SDK de Next; en Render se aceptan los dos.
    CLERK_PUBLISHABLE_KEY: str = Field(
        default="",
        validation_alias=AliasChoices(
            "CLERK_PUBLISHABLE_KEY",
            "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
        ),
    )
    CLERK_SECRET_KEY: str = ""
    #: URL de la Frontend API de Clerk (el `iss` de sus tokens). Si va vacía se
    #: deriva de la clave pública, que la lleva codificada.
    CLERK_ISSUER: str = ""
    #: Qué sesiones acepta la API (ADR-027): `own` (JWT propio, lo de siempre),
    #: `both` (transición: propio y Clerk) o `clerk` (solo Clerk; el registro y
    #: el login propios responden 410).
    AUTH_MODE: str = "own"
    #: Analizar cada documento al subirlo, en segundo plano (ADR-029). Los tests
    #: lo apagan para no llamar al modelo; los que lo prueban lo encienden.
    AUTO_ANALYZE_UPLOAD: bool = True
    #: Voz del tutor (ADR-026). Apagada por defecto: cada audio es un gasto.
    TTS_ENABLED: bool = False
    TTS_MODEL: str = "gpt-4o-mini-tts"
    TTS_VOICE: str = "coral"
    #: Caracteres por petición: una o dos frases. El cliente trocea la respuesta.
    TTS_MAX_CHARS: int = 1200
    FORGETTING_HALF_LIFE_DAYS: float = 14.0

    # Motor adaptativo (ADR-004). Son hipótesis nombradas, no constantes:
    # se calibran con datos de outcome, no se tocan a ojo.
    # Falso desde la fase D: la adaptación llega al prompt y `payload.explanation`
    # se le muestra al estudiante. Poner True vuelve al modo sombra —señales
    # computadas, prompt intacto—, que es el interruptor para apagarla sin
    # desplegar código si algo sale mal en producción.
    ADAPT_SHADOW_MODE: bool = False
    ADAPT_BAND_LOW: float = 0.34
    ADAPT_BAND_HIGH: float = 0.67
    ADAPT_CUT_ABANDONMENT: float = 0.55
    ADAPT_CUT_ATTENTION_SPAN: float = 0.6
    ADAPT_CUT_PREFERENCE: float = 0.4
    ADAPT_EWMA_ALPHA: float = 0.3
    ADAPT_LONG_EXPLANATION_CHARS: int = 900
    ADAPT_SESSION_GAP_MINUTES: int = 20
    ADAPT_MIN_SAMPLES: int = 5
    LOG_LEVEL: str = "INFO"  # DEBUG | INFO | WARNING | ERROR
    LOG_FORMAT: str = "text"  # text | json


def _is_wildcard_cors_origin(origin: str) -> bool:
    token = origin.strip().rstrip("/")
    return token in {"*", "null"} or token.endswith("*")


#: Orígenes que ningún patrón de CORS debe aceptar. Si el patrón deja pasar
#: alguno, la app no arranca: mejor un despliegue fallido que uno abierto sin
#: que nadie lo note.
_ORIGENES_HOSTILES = (
    "https://evil.example.com",
    "https://vercel.app",
    "https://attacker.vercel.app",
    "https://laria-frontend.vercel.app.evil.com",
    "http://laria-frontend.vercel.app",
)


def _validate_cors_regex(patron: str) -> None:
    """Un patrón de CORS mal escrito abre la API sin avisar; aquí se para.

    Límite honesto de lo que esto protege: Vercel da a cada proyecto el dominio
    `<nombre>.vercel.app` si está libre, así que alguien podría llamar a su
    proyecto como para que su URL encaje en el patrón. Aquí eso casi no importa,
    porque la API no usa cookies: la sesión va en un token Bearer que una página
    ajena no tiene, así que solo podría hacer peticiones anónimas, que puede
    hacer igual desde un servidor. CORS no es la barrera de esta API; el token sí.
    """
    import re as _re

    if not (patron.startswith("^") and patron.endswith("$")):
        raise RuntimeError(
            "CORS_ORIGIN_REGEX debe ir anclado con ^ y $: sin anclas, "
            "'https://laria-frontend.vercel.app.evil.com' también encajaría."
        )
    try:
        compilado = _re.compile(patron)
    except _re.error as exc:
        raise RuntimeError(f"CORS_ORIGIN_REGEX no es una expresión válida: {exc}") from exc
    for origen in _ORIGENES_HOSTILES:
        if compilado.fullmatch(origen):
            raise RuntimeError(
                f"CORS_ORIGIN_REGEX deja pasar {origen!r}: es demasiado amplio."
            )


def validate_security_settings(s: "Settings") -> None:
    """Impide arrancar la API con una SECRET_KEY vacía o conocida, o con un
    patrón de CORS que abra la API a orígenes ajenos.

    Genera una clave segura con: openssl rand -hex 32
    """
    if (s.CORS_ORIGIN_REGEX or "").strip():
        _validate_cors_regex(s.CORS_ORIGIN_REGEX.strip())
    if s.SECRET_KEY in _INSECURE_SECRET_KEYS or len(s.SECRET_KEY) < 32:
        raise RuntimeError(
            "SECRET_KEY insegura o ausente: define una clave de al menos 32 caracteres "
            "en la variable de entorno SECRET_KEY (p. ej. `openssl rand -hex 32`)."
        )


def validate_ia_settings(s: "Settings") -> None:
    """Exige proveedor OpenAI y API key."""
    provider = s.IA_PROVIDER.lower().strip()
    if provider != "openai":
        raise RuntimeError(
            f"IA_PROVIDER='{s.IA_PROVIDER}' no soportado. LARIA solo usa OpenAI "
            "(define IA_PROVIDER=openai)."
        )
    if not s.OPENAI_API_KEY or not s.OPENAI_API_KEY.strip():
        raise RuntimeError(
            "OPENAI_API_KEY ausente: define la clave de OpenAI en el entorno."
        )


def validate_runtime_settings(s: "Settings") -> None:
    """Fail-fast de producción: Mongo, outbox, docs cerrados."""
    env = (s.APP_ENV or "development").lower().strip()
    if env not in {"development", "production"}:
        raise RuntimeError("APP_ENV debe ser 'development' o 'production'.")
    almacen = (s.ORIGINAL_STORAGE or "blob").lower().strip()
    if almacen not in {"blob", "r2"}:
        raise RuntimeError("ORIGINAL_STORAGE debe ser 'blob' o 'r2'.")
    if almacen == "r2":
        # Mejor no arrancar que arrancar y perder los archivos de los alumnos
        # en el primer upload por una variable a medias.
        faltan = [
            nombre
            for nombre, valor in (
                ("R2_ENDPOINT_URL", s.R2_ENDPOINT_URL),
                ("R2_BUCKET", s.R2_BUCKET),
                ("R2_ACCESS_KEY_ID", s.R2_ACCESS_KEY_ID),
                ("R2_SECRET_ACCESS_KEY", s.R2_SECRET_ACCESS_KEY),
            )
            if not (valor or "").strip()
        ]
        if faltan:
            raise RuntimeError(
                "ORIGINAL_STORAGE=r2 exige " + ", ".join(faltan) + "."
            )
    if env == "production":
        if s.DB_PROVIDER != "mongodb":
            raise RuntimeError(
                "APP_ENV=production exige DB_PROVIDER=mongodb (memory no es multi-réplica)."
            )
        if not (s.MONGODB_URL or "").strip():
            raise RuntimeError("APP_ENV=production exige MONGODB_URL no vacío.")
        if s.ENABLE_DOCS:
            raise RuntimeError(
                "APP_ENV=production exige ENABLE_DOCS=false (Swagger no en producción)."
            )
        backend = (s.RATE_LIMIT_BACKEND or "memory").lower().strip()
        if backend not in {"memory", "redis"}:
            raise RuntimeError("RATE_LIMIT_BACKEND debe ser 'memory' o 'redis'.")
        bus = (s.EVENT_BUS_BACKEND or "memory").lower().strip()
        if bus not in {"memory", "outbox"}:
            raise RuntimeError("EVENT_BUS_BACKEND debe ser 'memory' o 'outbox'.")
        if bus != "outbox":
            raise RuntimeError(
                "APP_ENV=production con DB_PROVIDER=mongodb exige EVENT_BUS_BACKEND=outbox "
                "(durabilidad de evidencia pedagógica entre réplicas/reinicios)."
            )
        if backend != "redis":
            raise RuntimeError(
                "APP_ENV=production exige RATE_LIMIT_BACKEND=redis (rate limit compartido)."
            )
        cache = (s.CACHE_BACKEND or "memory").lower().strip()
        if cache not in {"memory", "redis"}:
            raise RuntimeError("CACHE_BACKEND debe ser 'memory' o 'redis'.")
        if cache != "redis":
            raise RuntimeError("APP_ENV=production exige CACHE_BACKEND=redis.")
        if not (s.REDIS_URL or "").strip():
            raise RuntimeError("APP_ENV=production exige REDIS_URL no vacío.")
        if not s.RATE_LIMIT_ENABLED:
            raise RuntimeError("APP_ENV=production exige RATE_LIMIT_ENABLED=true.")
        origins = [str(o).strip() for o in (s.CORS_ORIGINS or []) if str(o).strip()]
        if not origins:
            raise RuntimeError(
                "APP_ENV=production exige CORS_ORIGINS no vacío (orígenes del front real)."
            )
        if any(_is_wildcard_cors_origin(o) for o in origins):
            raise RuntimeError(
                "APP_ENV=production no admite CORS_ORIGINS comodín (*)."
            )


settings = Settings()


def clerk_issuer(s: "Settings | None" = None) -> str:
    """El `iss` de los tokens de Clerk: explícito, o sacado de la clave pública.

    `pk_test_<base64("glorious-bluejay-3695.clerk.accounts.dev$")>` lleva dentro
    la Frontend API; derivarla evita una variable más que se pueda desalinear.
    """
    import base64

    s = s or settings
    explicito = (s.CLERK_ISSUER or "").strip().rstrip("/")
    if explicito:
        return explicito
    clave = (s.CLERK_PUBLISHABLE_KEY or "").strip()
    if not clave.startswith(("pk_test_", "pk_live_")):
        return ""
    cuerpo = clave.split("_", 2)[2]
    try:
        host = base64.b64decode(cuerpo + "=" * (-len(cuerpo) % 4)).decode("ascii").rstrip("$")
    except Exception:  # noqa: BLE001 — clave mal copiada: Clerk queda apagado
        return ""
    return f"https://{host}" if host else ""


def clerk_enabled(s: "Settings | None" = None) -> bool:
    s = s or settings
    return (s.AUTH_MODE or "own").strip().lower() in {"both", "clerk"} and bool(clerk_issuer(s))
