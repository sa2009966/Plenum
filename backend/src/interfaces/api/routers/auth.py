from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from src.application.dto.user_dto import RegisterUserDTO
from src.application.services.user_service import UserService
from src.infrastructure.rate_limit import login_attempt_allowed
from src.infrastructure.security.jwt_tokens import create_access_token
from src.domain.ports.external_identity import ExternalIdentityVerifier, InvalidExternalToken
from src.infrastructure.config import settings
from src.interfaces.api.dependencies import get_google_verifier, get_user_service
from src.interfaces.api.openapi_responses import (
    RESP_401_UNAUTHORIZED,
    RESP_409_CONFLICT,
    RESP_422_VALIDATION,
    RESP_429_RATE_LIMIT,
)
from src.interfaces.schemas.user_schemas import (
    AuthProvidersResponse,
    GoogleLoginRequest,
    TokenResponse,
    UserRegisterRequest,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["Autenticación"])


def cuentas_propias_abiertas() -> None:
    """Con AUTH_MODE=clerk, registrarse o entrar sin Clerk no existe (ADR-050).

    Antes estas rutas seguían emitiendo el JWT propio aunque ya no abriera
    sesión: quedaban públicas, sin uso, como superficie para crear cuentas y
    probar contraseñas. 404 y no 403: para el cliente la ruta no está.
    """
    if (settings.AUTH_MODE or "own").strip().lower() == "clerk":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entra con tu cuenta de Plenum.")


_CUENTA_PROPIA = [Depends(cuentas_propias_abiertas)]


@router.post(
    "/register",
    dependencies=_CUENTA_PROPIA,
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar usuario",
    description=(
        "Crea una cuenta nueva con nombre de usuario, email y contraseña. "
        "No requiere JWT. Las contraseñas deben cumplir la longitud mínima definida en el esquema."
    ),
    response_description="Datos públicos del usuario recién creado (sin contraseña).",
    responses={
        **RESP_409_CONFLICT,
        **RESP_422_VALIDATION,
        **RESP_429_RATE_LIMIT,
    },
)
async def register(
    body: UserRegisterRequest,
    service: Annotated[UserService, Depends(get_user_service)],
):
    dto = RegisterUserDTO(
        username=body.username,
        email=body.email,
        password=body.password,
    )
    try:
        user = await service.register(dto)
    except ValueError as exc:
        detail = str(exc)
        # Conflicto de identidad → 409; contraseña débil u otra validación → 422.
        code = (
            status.HTTP_409_CONFLICT
            if detail.startswith("Ya existe")
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        raise HTTPException(status_code=code, detail=detail)
    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
    )


@router.post(
    "/token",
    dependencies=_CUENTA_PROPIA,
    response_model=TokenResponse,
    summary="Obtener token JWT (OAuth2 password)",
    description=(
        "Intercambio de credenciales por un `access_token` JWT. "
        "El campo `username` del formulario debe contener el **email** del usuario "
        "(compatibilidad con `OAuth2PasswordRequestForm`). "
        "Este endpoint no usa cabecera `Authorization`."
    ),
    response_description="Token Bearer para usar en `Authorization: Bearer <access_token>`.",
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_422_VALIDATION,
        **RESP_429_RATE_LIMIT,
    },
)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    service: Annotated[UserService, Depends(get_user_service)],
):
    if not await login_attempt_allowed(form.username):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos para esta cuenta. Espera 15 minutos y vuelve a intentarlo.",
            headers={"Retry-After": "900"},
        )
    try:
        user = await service.authenticate(form.username, form.password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(str(user.id))
    return TokenResponse(access_token=token)


@router.get(
    "/providers",
    response_model=AuthProvidersResponse,
    summary="Proveedores de acceso disponibles",
    description=(
        "Claves públicas para los botones de acceso. `null` si ese proveedor no está "
        "configurado. La clave secreta de Clerk no sale de aquí."
    ),
)
async def providers():
    return AuthProvidersResponse(
        google_client_id=settings.GOOGLE_CLIENT_ID.strip() or None,
        clerk_publishable_key=settings.CLERK_PUBLISHABLE_KEY.strip() or None,
    )


@router.post(
    "/google",
    dependencies=_CUENTA_PROPIA,
    response_model=TokenResponse,
    summary="Entrar con Google",
    description=(
        "Recibe el ID token (`credential`) del botón de Google Identity Services, lo verifica "
        "(firma, audiencia, emisor, caducidad y correo verificado) y devuelve el mismo JWT "
        "que `/auth/token`. Si no existe cuenta con ese correo, la crea. Si existe, la "
        "vincula; si su correo nunca se había verificado, su contraseña anterior se anula "
        "(evita el secuestro por pre-registro, ADR-025)."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_422_VALIDATION, **RESP_429_RATE_LIMIT},
)
async def google_login(
    body: GoogleLoginRequest,
    service: Annotated[UserService, Depends(get_user_service)],
    verifier: Annotated[ExternalIdentityVerifier, Depends(get_google_verifier)],
):
    try:
        identidad = await verifier.verify(body.id_token)
        user = await service.login_with_external(identidad)
    except (InvalidExternalToken, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenResponse(access_token=create_access_token(str(user.id)))
