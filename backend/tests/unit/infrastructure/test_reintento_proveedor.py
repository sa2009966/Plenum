"""Fallos pasajeros de OpenAI se reintentan; los demás fallan a la primera y quedan en el log.

"Le doy aceptar al quiz y dice error del proveedor de IA": el backend convertía
cualquier fallo (timeout, 429, 5xx, 400) en ese mensaje, sin reintentar y sin
registrar la causa, así que no había forma de saber qué pasó.
"""
import httpx
import pytest

import src.infrastructure.ia.base_chat_analyst as mod
from src.domain.ports.ia_analyst import IAAnalysisError
from src.infrastructure.ia.base_chat_analyst import BaseChatAnalyst

OK = {"choices": [{"message": {"content": "hola"}}], "usage": {}}


def _analista(respuestas, monkeypatch):
    monkeypatch.setattr(mod, "_ESPERAS_REINTENTO_S", (0.0, 0.0))
    llamadas = []

    class Cliente:
        async def post(self, url, headers=None, json=None):
            llamadas.append(1)
            r = respuestas.pop(0)
            if isinstance(r, Exception):
                raise r
            codigo, cuerpo = r
            return httpx.Response(codigo, json=cuerpo, request=httpx.Request("POST", url))

    a = BaseChatAnalyst.__new__(BaseChatAnalyst)
    a.model, a.api_url, a._headers, a._metrics = "gpt-4o-mini", "http://x", {}, None

    async def cliente():
        return Cliente()

    a._get_client = cliente
    return a, llamadas


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fallo",
    [
        (429, {"error": {"type": "rate_limit", "code": "rate_limit_exceeded"}}),
        (503, {"error": {"type": "server_error"}}),
        httpx.ReadTimeout("lento"),
        httpx.ConnectError("caído"),
    ],
)
async def test_lo_pasajero_se_reintenta(fallo, monkeypatch):
    a, llamadas = _analista([fallo, (200, OK)], monkeypatch)

    assert await a._chat("s", "u") == "hola"
    assert len(llamadas) == 2


@pytest.mark.asyncio
async def test_una_peticion_rechazada_no_se_reintenta_y_se_registra(monkeypatch, caplog):
    a, llamadas = _analista([(400, {"error": {"type": "invalid_request_error", "code": "bad"}})], monkeypatch)

    with pytest.raises(IAAnalysisError, match="no está disponible"):
        await a._chat("s", "u", task="quiz")
    assert len(llamadas) == 1
    assert "http=400" in caplog.text and "invalid_request_error" in caplog.text


@pytest.mark.asyncio
async def test_tres_429_seguidos_dicen_que_esta_saturado(monkeypatch):
    fallo = (429, {"error": {"type": "rate_limit"}})
    a, llamadas = _analista([fallo, fallo, fallo], monkeypatch)

    with pytest.raises(IAAnalysisError, match="muchas peticiones"):
        await a._chat("s", "u")
    assert len(llamadas) == 3


@pytest.mark.asyncio
async def test_el_log_no_lleva_la_clave(monkeypatch, caplog):
    a, _ = _analista([(401, {"error": {"type": "auth"}})], monkeypatch)
    a._headers = {"Authorization": "Bearer sk-secreta"}

    with pytest.raises(IAAnalysisError):
        await a._chat("s", "u")
    assert "sk-secreta" not in caplog.text


# --- Streaming: el chat del tutor y las dudas en clase (ADR-054) -------------------------
#
# El streaming no tenía ni reintentos ni log: cada 429 o 5xx pasajero de OpenAI llegaba
# al estudiante como «No pude generar la respuesta» y en Render no quedaba rastro.

SSE_OK = (
    'data: {"choices": [{"delta": {"content": "ho"}}]}\n\n'
    'data: {"choices": [{"delta": {"content": "la"}}]}\n\n'
    "data: [DONE]\n\n"
)


def _analista_stream(respuestas, monkeypatch):
    monkeypatch.setattr(mod, "_ESPERAS_REINTENTO_S", (0.0, 0.0))
    llamadas = []

    def responder(request):
        llamadas.append(1)
        r = respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        codigo, cuerpo = r
        if codigo == 200:
            return httpx.Response(200, text=cuerpo, headers={"content-type": "text/event-stream"})
        return httpx.Response(codigo, json=cuerpo)

    class Politica:
        def answer_question(self, *a, **k):
            class P:
                system, user = "s", "u"
            return P()

    a = BaseChatAnalyst.__new__(BaseChatAnalyst)
    a.model, a.api_url, a._headers, a._metrics, a._policy = "gpt-4o-mini", "http://x", {}, None, Politica()
    cliente = httpx.AsyncClient(transport=httpx.MockTransport(responder))

    async def get_cliente():
        return cliente

    a._get_client = get_cliente
    return a, llamadas


async def _texto(a):
    return "".join([t async for t in a.answer_question_stream("contexto", "pregunta")])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fallo",
    [
        (429, {"error": {"type": "rate_limit", "code": "rate_limit_exceeded"}}),
        (503, {"error": {"type": "server_error"}}),
        httpx.ReadTimeout("lento"),
        httpx.ConnectError("caído"),
    ],
)
async def test_en_streaming_lo_pasajero_se_reintenta(fallo, monkeypatch):
    a, llamadas = _analista_stream([fallo, (200, SSE_OK)], monkeypatch)

    assert await _texto(a) == "hola"
    assert len(llamadas) == 2


@pytest.mark.asyncio
async def test_en_streaming_una_peticion_rechazada_no_se_reintenta_y_se_registra(monkeypatch, caplog):
    a, llamadas = _analista_stream(
        [(400, {"error": {"type": "invalid_request_error", "code": "bad"}})], monkeypatch
    )

    with pytest.raises(IAAnalysisError, match="no está disponible"):
        await _texto(a)
    assert len(llamadas) == 1
    assert "task=ask" in caplog.text and "http=400" in caplog.text and "invalid_request_error" in caplog.text


@pytest.mark.asyncio
async def test_en_streaming_tres_429_seguidos_dicen_que_esta_saturado(monkeypatch):
    fallo = (429, {"error": {"type": "rate_limit"}})
    a, llamadas = _analista_stream([fallo, fallo, fallo], monkeypatch)

    with pytest.raises(IAAnalysisError, match="muchas peticiones"):
        await _texto(a)
    assert len(llamadas) == 3
