"""La marca `[[imagen: …]]` se cambia por una foto con licencia, o se quita (ADR-048, fase 2)."""
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.application.services.chat_tutor_service import ChatTutorService
from src.application.services.topic_catalog import TopicCatalog
from src.domain.services.visuals import LicensedImage

FOTO = LicensedImage(
    url="https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Ojo.jpg/800px-Ojo.jpg",
    page_url="https://commons.wikimedia.org/wiki/File:Ojo.jpg",
    title="Ojo humano", author="Ana", license="CC BY 4.0", license_url="https://creativecommons.org/licenses/by/4.0",
)
RESPUESTA = "El ojo enfoca con el cristalino.\n\n[[imagen: ojo humano]]\n\nLa retina recibe la luz."


class Buscador:
    def __init__(self, foto):
        self.foto, self.pedidas = foto, []

    async def find(self, query):
        self.pedidas.append(query)
        return self.foto


def _servicio(buscador=None):
    gate = AsyncMock()
    gate.answer_question = AsyncMock(return_value=RESPUESTA)

    async def stream(**kw):
        gate.ultimo = kw
        yield RESPUESTA

    gate.answer_question_stream = stream
    return ChatTutorService(llm_gate=gate, topic_catalog=TopicCatalog(), image_finder=buscador), gate


@pytest.mark.asyncio
async def test_con_buscador_la_foto_llega_con_su_atribucion():
    servicio, gate = _servicio(Buscador(FOTO))

    r = await servicio.answer(None, "dibújame el ojo", uuid4())

    assert FOTO.url in r.content and "[[imagen" not in r.content
    assert r.envelope.payload["visuals"] == [FOTO.to_dict()]
    assert gate.answer_question.await_args.kwargs["learner"].images is True


@pytest.mark.asyncio
async def test_en_streaming_el_cierre_trae_la_foto():
    buscador = Buscador(FOTO)
    servicio, gate = _servicio(buscador)

    trozos = [t async for t in servicio.answer_stream(None, "dibújame el ojo", uuid4())]
    final, envelope = trozos[-1]

    assert FOTO.url in final and envelope.payload["visuals"] == [FOTO.to_dict()]
    assert buscador.pedidas == ["ojo humano"] and gate.ultimo["learner"].images is True


@pytest.mark.asyncio
async def test_sin_buscador_o_sin_foto_la_marca_se_quita():
    for buscador in (None, Buscador(None)):
        servicio, gate = _servicio(buscador)
        r = await servicio.answer(None, "dibújame el ojo", uuid4())

        assert r.content == "El ojo enfoca con el cristalino.\n\nLa retina recibe la luz."
        assert "visuals" not in r.envelope.payload
        if buscador is None:
            learner = gate.answer_question.await_args.kwargs["learner"]
            assert not (learner and learner.images), "sin buscador no se le pide foto al modelo"


def test_el_buscador_solo_existe_con_interruptor_y_clave(monkeypatch):
    from src.infrastructure.config import settings
    from src.infrastructure.media.wikimedia_image_finder import WikimediaImageFinder
    from src.interfaces.api import dependencies as deps

    for activo, clave, esperado in ((False, "sk-x", None), (True, "", None), (True, "sk-x", WikimediaImageFinder)):
        monkeypatch.setattr(settings, "WIKIMEDIA_IMAGES_ENABLED", activo)
        monkeypatch.setattr(settings, "OPENAI_API_KEY", clave)
        deps.get_image_finder.cache_clear()
        finder = deps.get_image_finder()
        assert (finder is None) if esperado is None else isinstance(finder, esperado)
    deps.get_image_finder.cache_clear()
