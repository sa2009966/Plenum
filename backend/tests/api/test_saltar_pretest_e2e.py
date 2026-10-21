"""Empezar la clase sin pre-test (ADR-055, §3 bis).

El pre-test (la nivelación) se ofrece siempre al empezar un tema nuevo, pero no
bloquea: el alumno puede continuar sin hacerlo (ADR-006, ofrecer y no bloquear).
Antes, sin nivelación la clase respondía 409 y no había forma de seguir.
"""
import asyncio
from uuid import UUID

from src.interfaces.api import dependencies as deps
from tests.api.test_clase_e2e import (
    _auth,
    _correctas,
    _leccion,
    _nivelarse,
    _ruta,
    entorno,  # noqa: F401  (fixture)
)
from tests.api.test_tramos_e2e import _completar


def _saltar(c, h, path_id):
    return c.post(f"/api/v1/learning/paths/{path_id}/skip-placement", headers=h)


def test_sin_pretest_la_clase_empieza_por_el_tramo_basico(entorno):  # noqa: F811
    c, modelo = entorno
    h = _auth(c)
    ruta = _ruta(c, h, "python")
    assert ruta["teaching"]["phase"] == "assessment" and ruta["placement_skipped"] is False

    r = _saltar(c, h, ruta["id"])

    assert r.status_code == 200, r.text
    saltada = r.json()
    assert saltada["placement_skipped"] is True
    assert saltada["tiers"] == ["basico"]
    assert saltada["teaching"]["phase"] == "teaching"
    paso = _leccion(c, h, ruta["id"])
    assert paso["check"] is not None
    assert modelo.lecciones[-1].concept == paso["path"]["teaching"]["concept"]


def test_saltar_el_pretest_no_escribe_nada_en_el_perfil(entorno):  # noqa: F811
    """No medido no es medido en cero: saltarlo no es evidencia ni un nivel."""
    c, _ = entorno
    h = _auth(c)
    ruta = _ruta(c, h, "python")

    _saltar(c, h, ruta["id"])

    uid = UUID(c.get("/api/v1/users/me", headers=h).json()["id"])
    perfil = asyncio.run(deps.get_profile_repo().find_by_student(uid))
    assert perfil is None or perfil.level_for_topic("python") is None


def test_solo_se_salta_mientras_la_ruta_espera_el_pretest(entorno):  # noqa: F811
    c, _ = entorno
    h = _auth(c)
    ruta = _ruta(c, h, "python")
    _saltar(c, h, ruta["id"])

    assert _saltar(c, h, ruta["id"]).status_code == 409, "ya empezó"

    h2 = _auth(c)
    _nivelarse(c, h2, "python")
    nivelada = _ruta(c, h2, "python")
    assert _saltar(c, h2, nivelada["id"]).status_code == 409, "ya tiene nivelación"


def test_la_ruta_de_otro_no_existe(entorno):  # noqa: F811
    c, _ = entorno
    ruta = _ruta(c, _auth(c), "python")

    assert _saltar(c, _auth(c), ruta["id"]).status_code == 404
    assert _saltar(c, _auth(c), "00000000-0000-0000-0000-000000000000").status_code == 404


def test_si_hace_el_pretest_despues_su_nivel_manda(entorno):  # noqa: F811
    """El pre-test sigue disponible: si sale intermedio, se abre ese tramo sin repetir lo visto."""
    c, _ = entorno
    h = _auth(c)
    ruta = _ruta(c, h, "python")
    _saltar(c, h, ruta["id"])

    _nivelarse(c, h, "python")  # sale intermedio
    paso = _leccion(c, h, ruta["id"])

    assert paso["path"]["tiers"] == ["basico", "intermedio"]
    assert paso["path"]["placement_skipped"] is True


def test_saltar_el_pretest_no_salta_la_prueba_de_paso(entorno):  # noqa: F811
    c, _ = entorno
    h = _auth(c)
    ruta = _ruta(c, h, "python")
    _saltar(c, h, ruta["id"])

    _, final = _completar(c, h, ruta["id"])

    assert final["teaching"]["phase"] == "completed"
    assert final["tiers"] == ["basico"] and final["next_tier"] == "intermedio"
    prueba = c.post(f"/api/v1/learning/paths/{ruta['id']}/passage-test", headers=h)
    assert prueba.status_code == 201, "para abrir el tramo siguiente hace falta la prueba de paso"
    intento = c.post(f"/api/v1/quizzes/{prueba.json()['id']}/attempts", headers=h,
                     json={"answers": _correctas(prueba.json())}).json()
    assert intento["placement"]["level"] == "intermedio"
