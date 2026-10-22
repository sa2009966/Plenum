"""Los textos legales se sirven, y dicen la verdad sobre el sistema (ADR-019).

Un texto legal que se desincroniza del código es peor que no tenerlo: promete
algo que no se cumple. Por eso, además de comprobar que se sirven, estos tests
fallan si el sistema deja de hacer lo que el texto afirma.
"""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("slug", ["terminos", "privacidad", "cookies"])
def test_cada_texto_se_sirve_sin_sesion(client, slug):
    """Hay que poder leerlos ANTES de registrarse."""
    r = client.get(f"/api/v1/legal/{slug}")

    assert r.status_code == 200
    doc = r.json()
    assert doc["title"] and doc["markdown"]
    assert doc["version"], "cada versión lleva fecha: sin ella no se sabe qué se aceptó"


def test_la_lista_enumera_los_tres(client):
    assert {d["slug"] for d in client.get("/api/v1/legal").json()} == {
        "terminos", "privacidad", "cookies",
    }


def test_un_texto_con_huecos_no_se_da_por_completo(client):
    doc = client.get("/api/v1/legal/privacidad").json()

    if "[[COMPLETAR" in doc["markdown"]:
        assert doc["completo"] is False
        assert doc["pendiente"], "los huecos deben enumerarse para no olvidarlos"


@pytest.mark.parametrize("slug", ["terminos", "privacidad", "cookies"])
def test_los_textos_publicados_no_tienen_huecos(client, slug):
    """Ya están completos: un hueco nuevo los devolvería a borrador sin que nadie lo notara."""
    doc = client.get(f"/api/v1/legal/{slug}").json()

    assert doc["completo"] is True, doc["pendiente"]


def test_la_politica_de_privacidad_cumple_lo_minimo_del_aviso_de_privacidad(client):
    """Art. 24 de la Ley para la Protección de Datos Personales de El Salvador: domicilio,
    base legal, derechos ARCO-POL, autoridad y uso de cookies."""
    texto = client.get("/api/v1/legal/privacidad").json()["markdown"]

    for frase in ("San Salvador", "consentimiento", "portabilidad", "Agencia de Ciberseguridad del Estado", "/legal/cookies"):
        assert frase in texto, frase


def test_un_texto_inexistente_es_404(client):
    assert client.get("/api/v1/legal/otra-cosa").status_code == 404


# --- El texto dice la verdad ----------------------------------------------------------


def test_el_servidor_no_pone_cookies_como_dice_la_politica(client):
    """La política dice que el servidor de la aplicación no instala cookies: las
    únicas son las del inicio de sesión de Clerk, que las pone el frontend y el
    propio Clerk. Antes decía "Plenum no usa cookies", y dejó de ser cierto al
    entrar Clerk.

    Si alguien añade una cookie en el servidor, este test falla y obliga a
    actualizar la política antes de que la promesa deje de ser cierta.
    """
    texto = client.get("/api/v1/legal/cookies").json()["markdown"]
    assert "El servidor de la aplicación no instala cookies" in texto
    assert "__session" in texto and "Clerk" in texto

    s = uuid4().hex[:8]
    email = f"cookie_{s}@example.com"
    respuestas = [
        client.post("/api/v1/auth/register",
                    json={"username": f"c_{s}", "email": email, "password": "SecurePass1x"}),
        client.post("/api/v1/auth/token", data={"username": email, "password": "SecurePass1x"}),
        client.get("/health"),
    ]
    for r in respuestas:
        assert "set-cookie" not in {k.lower() for k in r.headers}, r.request.url


def test_el_borrado_de_cuenta_que_promete_la_politica_existe(client):
    """Privacidad y términos dicen que puedes borrar tu cuenta tú mismo."""
    assert "Borrar tu cuenta" in client.get("/api/v1/legal/privacidad").json()["markdown"]

    rutas = client.get("/openapi.json").json()["paths"]
    assert "delete" in rutas.get("/api/v1/users/me", {})


def test_la_politica_de_privacidad_nombra_a_clerk_y_no_a_google_fonts(client):
    texto = client.get("/api/v1/legal/privacidad").json()["markdown"]

    assert "**Clerk**" in texto
    assert "Google Fonts" not in texto, "la web ya sirve sus fuentes desde su dominio"
