import logging
from typing import Annotated, Optional
from urllib.parse import quote
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)

from src.application.dto.document_dto import UploadDocumentDTO
from src.application.file_parser import inline_safe_type, is_supported
from src.application.services.analyze_document_service import AnalyzeDocumentService
from src.application.services.document_service import (
    DocumentService,
    DocumentTooLargeError,
    UnsupportedFileError,
    mensaje_demasiado_grande,
)
from src.application.services.quiz_service import QuizService
from src.domain.ports.ia_analyst import IAAnalysisError
from src.domain.value_objects.subject import DEFAULT_SUBJECT
from src.infrastructure.config import settings
from src.interfaces.api.openapi_responses import (
    RESP_401_UNAUTHORIZED,
    RESP_404_NOT_FOUND,
    RESP_422_VALIDATION,
    RESP_429_RATE_LIMIT,
    RESP_502_BAD_GATEWAY,
)
from src.interfaces.api.dependencies import (
    get_analyze_service,
    get_current_user_id,
    get_document_service,
    get_quiz_service,
)
from src.interfaces.api.quiz_mappers import quiz_to_public_response
from src.interfaces.schemas.document_schemas import (
    AnalysisResponse,
    DocumentResponse,
    DocumentUploadRequest,
    QuestionRequest,
    QuestionResponse,
)
from src.interfaces.schemas.quiz_schemas import AssessmentOverride, QuizPublicResponse

logger = logging.getLogger("laria.documents")

router = APIRouter(prefix="/documents", tags=["Documentos"])

_MSG_NO_ENCONTRADO = "Recurso no encontrado"
try:
    _HTTP_413 = status.HTTP_413_CONTENT_TOO_LARGE
except AttributeError:  # pragma: no cover
    _HTTP_413 = 413
_RESUME_FORMATOS = (
    "Texto (.txt, .md, .csv, .json, .log), código (.py, .js, .ts, ...), "
    "PDF, Word (.docx), Excel (.xlsx), PowerPoint (.pptx)"
)
_RESP_413 = {
    _HTTP_413: {
        "description": "El archivo supera DOCUMENT_MAX_UPLOAD_BYTES (25 MB en producción).",
    }
}


def _map(doc) -> DocumentResponse:
    """Mapea DocumentDTO (o agregado) a respuesta HTTP."""
    subject = doc.subject.value if hasattr(doc.subject, "value") else str(doc.subject)
    status_val = doc.status.value if hasattr(doc.status, "value") else str(doc.status)
    has_analysis = doc.has_analysis() if callable(getattr(doc, "has_analysis", None)) else bool(doc.has_analysis)
    return DocumentResponse(
        id=str(doc.id),
        owner_id=str(doc.owner_id),
        filename=doc.filename,
        subject=subject,
        status=status_val,
        uploaded_at=doc.uploaded_at,
        has_analysis=has_analysis,
        error_message=doc.error_message,
    )


def _http_not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_MSG_NO_ENCONTRADO)


async def _analizar_en_segundo_plano(analyze: AnalyzeDocumentService, document_id, owner_id) -> None:
    """Analiza el documento recién subido sin hacer esperar al estudiante (ADR-029).

    Antes el análisis solo ocurría si el cliente llamaba a /analyze, y el
    cliente nunca lo hacía: los documentos se quedaban sin resumen ni conceptos
    y el tutor trabajaba a ciegas. Si esto falla o el servidor se duerme, el
    primer turno o quiz lo repite (`ensure_analysis`).
    """
    try:
        await analyze.execute(document_id, owner_id)
    except Exception:  # noqa: BLE001 — el respaldo lo reintenta
        logger.warning("analisis_en_segundo_plano_fallo doc=%s", document_id)


@router.post(
    "/",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Subir documento (texto JSON)",
    description=(
        "Registra un material educativo asociado al usuario del JWT. "
        "El contenido se envía como texto en JSON (máx. 100_000 caracteres). "
        "El cuerpo se almacena en DocumentBlobStore (GridFS si Mongo). "
        "Para archivos grandes use `POST /documents/upload` (multipart)."
    ),
    response_description="Metadatos del documento creado (incluye resultado de análisis previo si existiera).",
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_422_VALIDATION,
        **RESP_429_RATE_LIMIT,
        **_RESP_413,
    },
)
async def upload_document(
    body: DocumentUploadRequest,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[DocumentService, Depends(get_document_service)],
    background: BackgroundTasks,
    analyze: Annotated[AnalyzeDocumentService, Depends(get_analyze_service)],
):
    dto = UploadDocumentDTO(
        filename=body.filename,
        content=body.content,
        subject=(body.subject or "").strip() or DEFAULT_SUBJECT,
    )
    try:
        doc = await service.upload(UUID(current_user_id), dto)
    except DocumentTooLargeError as exc:
        raise HTTPException(
            status_code=_HTTP_413,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    if settings.AUTO_ANALYZE_UPLOAD:
        background.add_task(_analizar_en_segundo_plano, analyze, doc.id, UUID(current_user_id))
    return _map(doc)


@router.post(
    "/upload",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Subir documento (multipart; el límite lo fija DOCUMENT_MAX_UPLOAD_BYTES)",
    description=(
        "Sube material educativo como archivo multipart (`file`; `subject` y `filename` opcionales: sin materia se guarda \"General\"). "
        f"Límite: {settings.DOCUMENT_MAX_UPLOAD_BYTES} bytes (DOCUMENT_MAX_UPLOAD_BYTES). "
        f"Formatos soportados: {_RESUME_FORMATOS}. El blob va a GridFS (Mongo) o almacén en memoria."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_422_VALIDATION,
        **RESP_429_RATE_LIMIT,
        **_RESP_413,
    },
)
async def upload_document_multipart(
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[DocumentService, Depends(get_document_service)],
    background: BackgroundTasks,
    analyze: Annotated[AnalyzeDocumentService, Depends(get_analyze_service)],
    file: Annotated[UploadFile, File(description=f"Archivo ({_RESUME_FORMATOS})")],
    # Opcional: el chat sube solo `file`. Sin materia, "General" (ver Subject).
    subject: Annotated[Optional[str], Form(max_length=128)] = None,
    filename: Annotated[Optional[str], Form()] = None,
):
    name = (filename or file.filename or "material.txt").strip() or "material.txt"
    if not is_supported(name):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Formato no soportado. Se aceptan: {_RESUME_FORMATOS}.",
        )
    max_bytes = int(settings.DOCUMENT_MAX_UPLOAD_BYTES)
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=_HTTP_413,
            # Solo se leyó hasta el límite + 1: el tamaño real lo da la cabecera
            # del multipart (Starlette lo expone en `size`).
            detail=mensaje_demasiado_grande(file.size or len(data), max_bytes),
        )
    if not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="El archivo está vacío.",
        )
    try:
        doc = await service.upload_bytes(
            UUID(current_user_id),
            filename=name,
            data=data,
            subject=(subject or "").strip() or DEFAULT_SUBJECT,
        )
    except DocumentTooLargeError as exc:
        raise HTTPException(
            status_code=_HTTP_413,
            detail=str(exc),
        ) from exc
    except (UnsupportedFileError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    if settings.AUTO_ANALYZE_UPLOAD:
        background.add_task(_analizar_en_segundo_plano, analyze, doc.id, UUID(current_user_id))
    return _map(doc)


@router.get(
    "/",
    response_model=list[DocumentResponse],
    summary="Listar mis documentos",
    description="Devuelve solo los documentos cuyo `owner_id` coincide con el usuario autenticado.",
    response_description="Lista de documentos del propietario.",
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_429_RATE_LIMIT,
    },
)
async def list_my_documents(
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[DocumentService, Depends(get_document_service)],
):
    result = await service.list_by_owner(UUID(current_user_id))
    return [_map(d) for d in result.documents]


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Obtener documento por id",
    description=(
        "Recupera un documento solo si el solicitante es su propietario (`owner_id` = usuario del JWT)."
    ),
    response_description="Metadatos y estado de análisis del documento.",
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_404_NOT_FOUND,
        **RESP_429_RATE_LIMIT,
    },
)
async def get_document(
    document_id: UUID,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[DocumentService, Depends(get_document_service)],
):
    try:
        doc = await service.get_by_id(document_id, UUID(current_user_id))
    except (ValueError, PermissionError) as exc:
        raise _http_not_found(exc)
    return _map(doc)


def _content_disposition(filename: str) -> str:
    """`inline` con el nombre original, sin romper la cabecera.

    El nombre lo escribe el usuario: meterlo crudo entre comillas deja pasar
    comillas y saltos de línea a la cabecera, y los nombres con tilde —en español,
    casi todos— no son ASCII. Va un respaldo ASCII y el nombre real en RFC 5987.
    """
    nombre = (filename or "documento").replace("\r", " ").replace("\n", " ")
    ascii_ = nombre.encode("ascii", "replace").decode("ascii").replace('"', "'").replace("?", "_")
    return f"inline; filename=\"{ascii_}\"; filename*=UTF-8''{quote(nombre, safe='')}"


@router.get(
    "/{document_id}/content",
    summary="Contenido original del documento",
    description=(
        "El archivo tal como se subió, para previsualizarlo o descargarlo. Solo el "
        "propietario: cualquier otro recibe **404**, no 403, para no confirmar qué "
        "documentos existen.\n\n"
        "Los documentos sin original guardado (anteriores al ADR-012 o creados "
        "enviando texto) devuelven su texto extraído como `text/plain`.\n\n"
        "**Requiere `Authorization: Bearer`.** Un `<img src>` o `<iframe src>` no "
        "manda esa cabecera: descarga con `fetch` y muestra el resultado con "
        "`URL.createObjectURL`."
    ),
    responses={
        200: {"description": "Bytes del archivo con su Content-Type"},
        **RESP_401_UNAUTHORIZED,
        **RESP_404_NOT_FOUND,
    },
)
async def get_document_content(
    document_id: UUID,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[DocumentService, Depends(get_document_service)],
):
    try:
        archivo = await service.get_original(document_id, UUID(current_user_id))
    except (ValueError, PermissionError) as exc:
        raise _http_not_found(exc)

    tipo = inline_safe_type(archivo.content_type)
    cabeceras = {
        "Content-Disposition": _content_disposition(archivo.filename),
        "Cache-Control": "private, max-age=3600",
        # Sin esto el navegador podría "adivinar" que un texto es HTML y
        # ejecutarlo, deshaciendo lo que hace `inline_safe_type`.
        "X-Content-Type-Options": "nosniff",
    }
    if not tipo.startswith("application/pdf"):
        # Defensa en profundidad para todo lo demás. El PDF queda fuera porque el
        # visor de PDF de Chromium no renderiza dentro de un documento sandbox.
        cabeceras["Content-Security-Policy"] = "sandbox"
    return Response(content=archivo.data, media_type=tipo, headers=cabeceras)


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar documento",
    description="Borra el documento si y solo si el usuario autenticado es el propietario.",
    response_description="Sin cuerpo en caso de éxito.",
    responses={
        status.HTTP_204_NO_CONTENT: {
            "description": "Documento eliminado; no se devuelve JSON.",
        },
        **RESP_401_UNAUTHORIZED,
        **RESP_404_NOT_FOUND,
        **RESP_429_RATE_LIMIT,
    },
)
async def delete_document(
    document_id: UUID,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[DocumentService, Depends(get_document_service)],
):
    try:
        await service.delete(document_id, UUID(current_user_id))
    except (ValueError, PermissionError) as exc:
        raise _http_not_found(exc)


@router.post(
    "/{document_id}/analyze",
    response_model=AnalysisResponse,
    summary="Analizar documento con IA",
    description=(
        "Solo el propietario del documento puede analizarlo. "
        "Si ya existe `analysis_result` guardado, se reutiliza la respuesta (sin llamar a la API de IA) "
        "salvo que se envíe `force_refresh=true`."
    ),
    response_description="Resumen, conceptos clave y preguntas sugeridas.",
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_404_NOT_FOUND,
        **RESP_422_VALIDATION,
        **RESP_429_RATE_LIMIT,
        **RESP_502_BAD_GATEWAY,
    },
)
async def analyze_document(
    document_id: UUID,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[AnalyzeDocumentService, Depends(get_analyze_service)],
    force_refresh: bool = Query(
        False,
        description="Si es true, ignora el análisis cacheado y vuelve a invocar a la IA.",
    ),
):
    try:
        analysis = await service.execute(document_id, UUID(current_user_id), force_refresh=force_refresh)
    except (ValueError, PermissionError) as exc:
        raise _http_not_found(exc)
    except IAAnalysisError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return AnalysisResponse(
        summary=analysis.summary,
        key_concepts=list(analysis.key_concepts),
        suggested_questions=list(analysis.suggested_questions),
    )


@router.post(
    "/{document_id}/ask",
    response_model=QuestionResponse,
    summary="Preguntar sobre el documento",
    description=(
        "Responde en lenguaje natural usando el texto del documento como contexto exclusivo. "
        "La interacción se registra como evidencia de aprendizaje. "
        "Solo el propietario del documento puede usar este endpoint."
    ),
    response_description="Respuesta del tutor virtual.",
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_404_NOT_FOUND,
        **RESP_422_VALIDATION,
        **RESP_429_RATE_LIMIT,
        **RESP_502_BAD_GATEWAY,
    },
)
async def ask_question(
    document_id: UUID,
    body: QuestionRequest,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[AnalyzeDocumentService, Depends(get_analyze_service)],
):
    try:
        answer = await service.answer_question(document_id, body.question, UUID(current_user_id))
    except (ValueError, PermissionError) as exc:
        raise _http_not_found(exc)
    except IAAnalysisError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return QuestionResponse(answer=answer)


@router.post(
    "/{document_id}/quiz",
    response_model=QuizPublicResponse,
    summary="Generar cuestionario",
    description=(
        "Genera y persiste un cuestionario de comprensión. "
        "La respuesta NO incluye las respuestas correctas (se revelan al enviar el intento). "
        "Parámetro opcional `num_questions` (1-20). Solo el propietario puede invocarlo."
    ),
    response_description="Quiz persistido con id y preguntas sin respuestas correctas.",
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_404_NOT_FOUND,
        **RESP_422_VALIDATION,
        **RESP_429_RATE_LIMIT,
        **RESP_502_BAD_GATEWAY,
    },
)
async def generate_quiz(
    document_id: UUID,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[QuizService, Depends(get_quiz_service)],
    num_questions: int = Query(
        5,
        ge=1,
        le=20,
        description="Cantidad de preguntas a generar (1-20). Con las abiertas activas manda la mezcla.",
    ),
    body: Optional[AssessmentOverride] = None,
):
    try:
        quiz = await service.generate(
            document_id, UUID(current_user_id), num_questions=num_questions,
            assessment=body.mix() if body else None,
        )
    except (ValueError, PermissionError) as exc:
        raise _http_not_found(exc)
    except IAAnalysisError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return quiz_to_public_response(quiz)
