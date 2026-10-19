"""Cada endpoint de la API aparece en docs/endpoints.md.

El catálogo se quedó atrás dos veces sin que nada avisara: en octubre le faltaban 12
rutas (voz, prueba de paso, metas y tiempo de estudio…) y el frontend las buscaba ahí.
Este test convierte "documentar el endpoint" en parte del contrato.
"""
import re
from pathlib import Path

from src.main import app

DOC = Path(__file__).resolve().parents[2] / "docs" / "endpoints.md"


def _norma(ruta: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", ruta).rstrip("/")


def test_todas_las_rutas_estan_en_el_catalogo():
    texto = DOC.read_text(encoding="utf-8")
    documentadas = {_norma(r) for r in re.findall(r"`(?:GET|POST|PUT|PATCH|DELETE)` \| `([^`]+)`", texto)}
    faltan = [
        f"{metodo.upper()} {ruta}"
        for ruta, ops in app.openapi()["paths"].items()
        for metodo in ops
        if ruta.startswith("/api/v1") and _norma(ruta) not in documentadas
    ]
    assert not faltan, f"Rutas sin documentar en docs/endpoints.md: {faltan}"
