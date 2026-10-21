"""Fotos de Wikimedia Commons con licencia libre, moderadas antes de entregarlas (ADR-048, fase 2).

Nunca rompe una respuesta: sin resultados, con un timeout o con la moderación caída,
devuelve None y la marca se quita. Con la moderación caída falla CERRADO (sin foto):
Commons no filtra por edad y hay estudiantes menores.
"""
from __future__ import annotations

import logging
import re
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping

import httpx

from src.domain.services.visuals import LicensedImage, image_is_safe, is_free_license

logger = logging.getLogger("laria.images")

_API = "https://commons.wikimedia.org/w/api.php"
#: La política de Wikimedia pide identificarse; sin correo personal.
_USER_AGENT = "LARIA-Plenum/1.0 (https://github.com/sa2009966/Plenum)"
_TIMEOUT_S = 4.0
_CANDIDATAS = 6
_ANCHO = 800
_MIMES = frozenset({"image/jpeg", "image/png", "image/webp"})
_CACHE_MAX = 500
_CACHE_TTL_S = 7 * 24 * 3600

ModerateImage = Callable[[str], Awaitable[Mapping[str, float]]]


def _texto(meta: dict, clave: str) -> str:
    valor = (meta.get(clave) or {}).get("value") or ""
    return re.sub(r"<[^>]*>", "", str(valor)).strip()


def _titulo(pagina: dict) -> str:
    titulo = str(pagina.get("title") or "")
    titulo = re.sub(r"^File:", "", titulo)
    return re.sub(r"\.(jpe?g|png|webp|gif|svg|tiff?)$", "", titulo, flags=re.I).replace("_", " ")


def candidates_from(data: dict) -> list[LicensedImage]:
    """Las fotos libres de una respuesta de la API, en el orden de la búsqueda. Pura."""
    paginas = sorted(((data.get("query") or {}).get("pages") or {}).values(), key=lambda p: p.get("index", 0))
    out: list[LicensedImage] = []
    for p in paginas:
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        licencia = _texto(meta, "LicenseShortName")
        url = info.get("thumburl") or info.get("url") or ""
        if info.get("mime") not in _MIMES or not is_free_license(licencia) or not url:
            continue
        out.append(
            LicensedImage(
                url=url,
                page_url=info.get("descriptionurl") or "",
                title=_titulo(p),
                author=_texto(meta, "Artist") or _texto(meta, "Credit"),
                license=licencia,
                license_url=_texto(meta, "LicenseUrl"),
            )
        )
    return out


class WikimediaImageFinder:
    def __init__(self, moderate: ModerateImage, http_client: httpx.AsyncClient | None = None) -> None:
        self._moderate = moderate
        self._client = http_client
        self._cache: OrderedDict[str, tuple[float, LicensedImage | None]] = OrderedDict()

    async def find(self, query: str) -> LicensedImage | None:
        clave = query.strip().lower()
        if not clave:
            return None
        guardada = self._cache.get(clave)
        if guardada and time.monotonic() - guardada[0] < _CACHE_TTL_S:
            return guardada[1]
        try:
            imagen = await self._buscar(clave)
        except Exception as exc:  # noqa: BLE001 — una foto nunca tumba la respuesta
            logger.warning("imagen_fallo query=%r %s", clave, type(exc).__name__)
            return None  # sin guardar: se reintenta la próxima vez
        self._cache[clave] = (time.monotonic(), imagen)
        self._cache.move_to_end(clave)
        while len(self._cache) > _CACHE_MAX:
            self._cache.popitem(last=False)
        return imagen

    async def _buscar(self, query: str) -> LicensedImage | None:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=_TIMEOUT_S)
        r = await self._client.get(
            _API,
            headers={"User-Agent": _USER_AGENT},
            params={
                "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
                "gsrsearch": f"{query} filetype:bitmap", "gsrlimit": _CANDIDATAS,
                "prop": "imageinfo", "iiprop": "url|mime|extmetadata", "iiurlwidth": _ANCHO,
            },
        )
        r.raise_for_status()
        for candidata in candidates_from(r.json()):
            # Moderación caída → excepción → sin foto (falla cerrado).
            if image_is_safe(dict(await self._moderate(candidata.url))):
                return candidata
            logger.info("imagen_moderada_rechazada query=%r", query)
        return None
