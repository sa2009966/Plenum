"""Buscador de fotos de Wikimedia: licencia libre, moderada y sin romper nunca la respuesta."""
import json

import httpx
import pytest

from src.domain.ports.content_moderator import ModerationUnavailable
from src.infrastructure.media.wikimedia_image_finder import WikimediaImageFinder, candidates_from
from src.infrastructure.openai.openai_moderator import OpenAIModerator


def _pagina(i, licencia="CC BY-SA 4.0", mime="image/jpeg", titulo="File:Volcán_Villarrica.jpg"):
    return {
        "index": i,
        "title": titulo,
        "imageinfo": [{
            "mime": mime,
            "thumburl": f"https://upload.wikimedia.org/wikipedia/commons/thumb/{i}.jpg",
            "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{i}.jpg",
            "extmetadata": {
                "LicenseShortName": {"value": licencia},
                "Artist": {"value": '<a href="//x">Ana Pérez</a>'},
                "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"},
            },
        }],
    }


RESPUESTA = {"query": {"pages": {
    "3": _pagina(3),
    "1": _pagina(1, licencia="CC BY-NC 4.0"),
    "2": _pagina(2, mime="image/svg+xml"),
}}}


def test_solo_salen_fotos_libres_en_el_orden_de_la_busqueda():
    fotos = candidates_from(RESPUESTA)

    assert [f.url.rsplit("/", 1)[1] for f in fotos] == ["3.jpg"]
    assert fotos[0].author == "Ana Pérez" and fotos[0].title == "Volcán Villarrica"
    assert candidates_from({}) == []


def _buscador(respuestas, moderar):
    llamadas = []

    def responder(request):
        llamadas.append(request)
        r = respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return httpx.Response(200, json=r)

    return WikimediaImageFinder(moderar, httpx.AsyncClient(transport=httpx.MockTransport(responder))), llamadas


async def _limpia(url):
    return {"sexual": 0.0}


@pytest.mark.asyncio
async def test_devuelve_la_primera_foto_libre_y_moderada_y_la_guarda():
    data = {"query": {"pages": {"1": _pagina(1), "2": _pagina(2)}}}
    finder, llamadas = _buscador([data], _limpia)

    foto = await finder.find("Volcán")
    otra = await finder.find("volcán ")

    assert foto is not None and foto.url.endswith("/1.jpg") and otra == foto
    assert len(llamadas) == 1, "la segunda vez sale de la caché"
    assert llamadas[0].headers["User-Agent"].startswith("LARIA")


@pytest.mark.asyncio
async def test_lo_que_la_moderacion_rechaza_se_salta():
    data = {"query": {"pages": {"1": _pagina(1), "2": _pagina(2)}}}

    async def moderar(url):
        return {"sexual": 0.9} if url.endswith("/1.jpg") else {"sexual": 0.0}

    finder, _ = _buscador([data], moderar)

    assert (await finder.find("ojo")).url.endswith("/2.jpg")


@pytest.mark.asyncio
async def test_con_la_moderacion_caida_no_hay_foto():
    async def caida(url):
        raise ModerationUnavailable("timeout")

    finder, _ = _buscador([{"query": {"pages": {"1": _pagina(1)}}}], caida)

    assert await finder.find("ojo") is None


@pytest.mark.asyncio
async def test_un_fallo_de_red_no_rompe_ni_se_guarda():
    finder, llamadas = _buscador([httpx.ConnectError("caído"), {"query": {"pages": {"1": _pagina(1)}}}], _limpia)

    assert await finder.find("ojo") is None
    assert await finder.find("ojo") is not None
    assert len(llamadas) == 2


@pytest.mark.asyncio
async def test_la_moderacion_de_imagen_manda_la_url_como_imagen():
    enviados = []

    def responder(request):
        enviados.append(json.loads(request.content))
        return httpx.Response(200, json={"results": [{"category_scores": {"sexual": 0.01}}]})

    m = OpenAIModerator("k", http_client=httpx.AsyncClient(transport=httpx.MockTransport(responder)))

    assert await m.image_scores("https://upload.wikimedia.org/x.jpg") == {"sexual": 0.01}
    assert enviados[0]["input"] == [{"type": "image_url", "image_url": {"url": "https://upload.wikimedia.org/x.jpg"}}]
    assert await m.scores("hola") == {"sexual": 0.01} and enviados[1]["input"] == "hola"
