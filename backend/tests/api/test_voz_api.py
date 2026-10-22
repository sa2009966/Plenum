"""POST /speech: leer en voz alta un trozo de la respuesta del tutor (ADR-026)."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.domain.ports.embodiment import AffectState, TextToSpeechPort
from src.infrastructure.config import settings
from src.interfaces.api import dependencies as deps
from src.main import app
from tests.conftest import clear_dependency_caches


class VozFalsa(TextToSpeechPort):
    def __init__(self, falla=False):
        self.recibido = []
        self.voces = []
        self.falla = falla

    async def stream(self, text, affect, voice=None):
        from src.infrastructure.embodiment.openai_tts import VoiceUnavailable

        self.recibido.append((text, affect))
        self.voces.append(voice)
        if self.falla:
            raise VoiceUnavailable("caída")
        yield b"ID3"
        yield b"mp3"

    async def synthesize(self, text, affect):
        return b"ID3mp3"


@pytest.fixture
def voz():
    return VozFalsa()


@pytest.fixture
def client(voz, monkeypatch):
    clear_dependency_caches()
    monkeypatch.setattr(settings, "TTS_ENABLED", True)
    app.dependency_overrides[deps.get_text_to_speech] = lambda: voz
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    clear_dependency_caches()


def _h(c):
    s = uuid4().hex[:8]
    email = f"v_{s}@example.com"
    c.post("/api/v1/auth/register", json={"username": f"v_{s}", "email": email, "password": "Clave123"})
    return {"Authorization": "Bearer " + c.post("/api/v1/auth/token", data={"username": email, "password": "Clave123"}).json()["access_token"]}


def test_devuelve_mp3_del_texto_hablable_con_el_tono_del_envelope(client, voz):
    r = client.post("/api/v1/speech", headers=_h(client), json={"text": "La **célula** es \\(\\frac{1}{2}\\).", "emotion": "patient"})

    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"
    assert r.content == b"ID3mp3"
    texto, afecto = voz.recibido[0]
    assert "**" not in texto and "frac" not in texto and "célula" in texto
    assert afecto == AffectState.PATIENT


def test_solo_codigo_no_tiene_nada_que_leer_salvo_el_aviso(client, voz):
    r = client.post("/api/v1/speech", headers=_h(client), json={"text": "```\nx=1\n```"})

    assert r.status_code == 200 and "código en pantalla" in voz.recibido[0][0]


def test_demasiado_largo_se_pide_por_partes(client, monkeypatch):
    monkeypatch.setattr(settings, "TTS_MAX_CHARS", 20)

    r = client.post("/api/v1/speech", headers=_h(client), json={"text": "Una frase bastante más larga que veinte."})
    assert r.status_code == 422


def test_si_el_proveedor_falla_es_503_con_json(client):
    app.dependency_overrides[deps.get_text_to_speech] = lambda: VozFalsa(falla=True)

    r = client.post("/api/v1/speech", headers=_h(client), json={"text": "Hola."})
    assert r.status_code == 503 and "no está disponible" in r.json()["detail"]


def test_apagada_es_503_y_config_lo_dice(client, monkeypatch):
    monkeypatch.setattr(settings, "TTS_ENABLED", False)

    assert client.get("/api/v1/speech/config").json()["enabled"] is False
    assert client.post("/api/v1/speech", headers=_h(client), json={"text": "Hola."}).status_code == 503


def test_sin_sesion_es_401(client):
    assert client.post("/api/v1/speech", json={"text": "Hola."}).status_code == 401


def test_hay_tres_voces_masculinas_y_tres_femeninas(client):
    r = client.get("/api/v1/speech/voices", headers=_h(client)).json()

    generos = [v["gender"] for v in r["voices"]]
    assert generos.count("masculina") == 3 and generos.count("femenina") == 3
    assert r["selected"] is None and r["default"] == "coral"


def test_elegir_voz_la_guarda_en_el_perfil_y_se_usa(client, voz):
    h = _h(client)

    assert client.put("/api/v1/speech/voice", headers=h, json={"voice": "cedar"}).json() == {"voice": "cedar"}
    assert client.get("/api/v1/speech/voices", headers=h).json()["selected"] == "cedar"
    client.post("/api/v1/speech", headers=h, json={"text": "Hola."})
    assert voz.voces[-1] == "cedar"


def test_la_vista_previa_usa_la_voz_pedida_sin_cambiar_la_elegida(client, voz):
    h = _h(client)
    client.put("/api/v1/speech/voice", headers=h, json={"voice": "cedar"})

    client.post("/api/v1/speech", headers=h, json={"text": "Hola.", "voice": "nova"})

    assert voz.voces[-1] == "nova"
    assert client.get("/api/v1/speech/voices", headers=h).json()["selected"] == "cedar"


def test_sin_eleccion_se_usa_la_de_por_defecto_y_null_la_restablece(client, voz):
    h = _h(client)
    client.post("/api/v1/speech", headers=h, json={"text": "Hola."})
    assert voz.voces[-1] == "coral"

    client.put("/api/v1/speech/voice", headers=h, json={"voice": "ash"})
    client.put("/api/v1/speech/voice", headers=h, json={"voice": None})
    assert client.get("/api/v1/speech/voices", headers=h).json()["selected"] is None


@pytest.mark.parametrize("ruta, cuerpo", [("/api/v1/speech/voice", {"voice": "darth"}), ("/api/v1/speech", {"text": "Hola.", "voice": "darth"})])
def test_una_voz_inexistente_es_422(client, ruta, cuerpo):
    metodo = client.put if ruta.endswith("voice") else client.post
    assert metodo(ruta, headers=_h(client), json=cuerpo).status_code == 422


def test_las_voces_traen_frase_de_muestra_por_genero(client):
    r = client.get("/api/v1/speech/voices", headers=_h(client)).json()

    assert "tu tutor de" in r["sample_texts"]["masculina"] and "tu tutora de" in r["sample_texts"]["femenina"]


@pytest.mark.asyncio
async def test_cortar_el_audio_cierra_el_generador_de_la_voz(monkeypatch):
    """Producción, 22-oct-2026: al cortar el audio quedaba abierto el generador interno
    («aclose(): asynchronous generator is already running»). Ahora se cierra en la
    misma tarea, aunque el cliente se vaya a mitad."""
    from src.infrastructure.config import settings
    from src.interfaces.api.routers import speech

    cerrado = []

    class Voz:
        async def stream(self, text, affect, voice=None):
            try:
                for trozo in (b"uno", b"dos", b"tres"):
                    yield trozo
            finally:
                cerrado.append(True)

    class Prefs:
        async def voice(self, _):
            return None

    monkeypatch.setattr(settings, "TTS_ENABLED", True)
    respuesta = await speech.speak(speech.SpeechRequest(text="Una frase para leer."), str(uuid4()), Voz(), Prefs())
    cuerpo = respuesta.body_iterator
    assert await cuerpo.__anext__() == b"uno"
    await cuerpo.aclose()  # el cliente corta el audio
    assert cerrado == [True]
