"""La ruta crece por tramos (ADR-037), de punta a punta por HTTP.

Antes la ruta se congelaba con su temario inicial: tras ~6 módulos no había más
clases, y pasar de básico a intermedio no añadía nada. Ahora la nivelación del
tema es la prueba de paso: al superarla, la ruta abre el tramo del nuevo nivel con
temario nuevo, sin repetir lo visto, y una ruta completada se reabre.
"""
from src.domain.ports.lesson_generator import SyllabusItem
from src.interfaces.api import dependencies as deps
from tests.api.test_clase_e2e import (
    _auth,
    _comprobar,
    _correctas,
    _leccion,
    _nivelarse,
    _ruta,
    entorno,  # noqa: F401  (fixture)
)


def _completar(c, h, path_id, maximo=40):
    """Da clases y acierta hasta que la ruta (o el tramo) queda completada."""
    vistos = []
    for _ in range(maximo):
        paso = _leccion(c, h, path_id)
        if paso["check"] is None:
            return vistos, paso["path"]
        vistos.append(paso["path"]["teaching"]["concept"])
        _comprobar(c, h, path_id, paso["check"], _correctas(paso["check"]))
    raise AssertionError("la ruta no terminó")


def test_basico_completo_ofrece_la_prueba_de_paso_y_al_superarla_crece(entorno):  # noqa: F811
    c, modelo = entorno
    h = _auth(c)
    _nivelarse(c, h, "python", bien=False)  # básico
    ruta = _ruta(c, h, "python")
    assert ruta["tiers"] == ["basico"] and ruta["next_tier"] == "intermedio"
    assert {m["tier"] for m in ruta["modules"]} == {"basico"}

    vistos, fin = _completar(c, h, ruta["id"])
    assert vistos == ["variables", "bucles"]
    assert fin["teaching"]["phase"] == "completed" and fin["next_tier"] == "intermedio"
    assert "prueba de paso" in fin["teaching"]["reason"]

    # Prueba de paso: la ronda base, superada → intermedio.
    assert _nivelarse(c, h, "python")["level"] == "intermedio"
    paso = _leccion(c, h, ruta["id"])

    ruta = paso["path"]
    assert ruta["tiers"] == ["basico", "intermedio"] and ruta["next_tier"] == "avanzado"
    nuevos = [m for m in ruta["modules"] if m["tier"] == "intermedio"]
    # El modelo repitió "Variables": se descarta. Lo nuevo va después de lo visto.
    assert [m["title"] for m in nuevos] == ["Patrones intermedio", "Diseño intermedio"]
    assert [m["position"] for m in nuevos] == [2, 3]
    assert nuevos[1]["prerequisites"] == [nuevos[0]["concept"]]
    nivel, vistos_antes = modelo.tramos[0]
    assert nivel == "intermedio" and vistos_antes == ("Variables", "Bucles")
    # La clase sigue, y el módulo intermedio se explica a nivel intermedio.
    assert ruta["teaching"]["phase"] != "completed" and paso["check"] is not None
    assert ruta["teaching"]["concept"] == nuevos[0]["concept"]
    assert modelo.lecciones[-1].level == "intermedio"


def test_tres_tramos_hasta_completar_la_ruta_de_verdad(entorno):  # noqa: F811
    c, modelo = entorno
    h = _auth(c)
    _nivelarse(c, h, "python", bien=False)
    ruta = _ruta(c, h, "python")
    _completar(c, h, ruta["id"])
    _nivelarse(c, h, "python")  # → intermedio
    vistos, _ = _completar(c, h, ruta["id"])
    assert vistos == ["patrones intermedio", "diseno intermedio"]

    assert _nivelarse(c, h, "python")["level"] == "avanzado"  # ronda avanzada
    vistos, fin = _completar(c, h, ruta["id"])

    assert vistos == ["patrones avanzado", "diseno avanzado"]
    assert fin["tiers"] == ["basico", "intermedio", "avanzado"]
    assert fin["next_tier"] is None and fin["teaching"]["reason"] == "Completaste la ruta."
    assert len(fin["modules"]) == 6
    # El tramo avanzado no repite lo anterior: se le pasó todo lo visto.
    assert modelo.tramos[-1][1] == ("Variables", "Bucles", "Patrones intermedio", "Diseño intermedio")


def test_quien_llega_intermedio_empieza_en_el_tramo_intermedio(entorno):  # noqa: F811
    c, _ = entorno
    h = _auth(c)
    _nivelarse(c, h, "python")  # supera la base → intermedio
    ruta = _ruta(c, h, "python")
    assert ruta["tiers"] == ["intermedio"] and ruta["next_tier"] == "avanzado"
    assert {m["tier"] for m in ruta["modules"]} == {"intermedio"}


def test_si_el_modelo_falla_el_tramo_no_se_abre_y_se_reintenta(entorno):  # noqa: F811
    c, modelo = entorno
    h = _auth(c)
    _nivelarse(c, h, "python", bien=False)
    ruta = _ruta(c, h, "python")
    _completar(c, h, ruta["id"])
    _nivelarse(c, h, "python")

    original = modelo.propose_syllabus

    async def caido(label, level, avoid=()):
        raise RuntimeError("proveedor caído")

    modelo.propose_syllabus = caido
    paso = _leccion(c, h, ruta["id"])
    assert paso["check"] is None and paso["path"]["tiers"] == ["basico"]

    modelo.propose_syllabus = original
    paso = _leccion(c, h, ruta["id"])
    assert paso["path"]["tiers"] == ["basico", "intermedio"] and paso["check"] is not None


def test_un_tramo_sin_nada_nuevo_no_se_abre(entorno):  # noqa: F811
    c, modelo = entorno
    h = _auth(c)
    _nivelarse(c, h, "python", bien=False)
    ruta = _ruta(c, h, "python")
    _completar(c, h, ruta["id"])
    _nivelarse(c, h, "python")

    async def repetido(label, level, avoid=()):
        return [SyllabusItem(t) for t in avoid]

    modelo.propose_syllabus = repetido
    paso = _leccion(c, h, ruta["id"])
    assert paso["path"]["tiers"] == ["basico"] and paso["path"]["teaching"]["phase"] == "completed"


def test_una_ruta_anterior_a_los_tramos_es_el_tramo_basico_y_puede_crecer(entorno):  # noqa: F811
    c, _ = entorno
    h = _auth(c)
    _nivelarse(c, h, "python", bien=False)
    ruta = _ruta(c, h, "python")
    _completar(c, h, ruta["id"])

    # Como las rutas guardadas antes de ADR-037: sin tramos ni tramo por módulo.
    import asyncio
    from uuid import UUID

    repo = deps.get_learning_path_repo()
    guardada = asyncio.run(repo.find_by_id(UUID(ruta["id"])))
    guardada.tiers = []
    for m in guardada.modules:
        m.tier = ""
    asyncio.run(repo.save(guardada))

    _nivelarse(c, h, "python")  # → intermedio
    paso = _leccion(c, h, ruta["id"])
    assert paso["path"]["tiers"] == ["basico", "intermedio"]
    assert [m["tier"] for m in paso["path"]["modules"]][:2] == ["basico", "basico"]


def test_la_sugerencia_de_subir_de_nivel_habla_del_tramo(entorno):  # noqa: F811
    c, _ = entorno
    h = _auth(c)
    _nivelarse(c, h, "python", bien=False)
    ruta = _ruta(c, h, "python")
    _completar(c, h, ruta["id"])
    s = c.get(f"/api/v1/learning/paths/{ruta['id']}/next", headers=h).json()["suggestions"]
    assert s[0]["kind"] == "level_up" and "tramo intermedio" in s[0]["reason"]
