"""El método de estudio cambia cómo se arma el paso (ADR-055, fase 4).

El modelo es un doble que escribe exactamente lo que el backend le pide: lo que se
comprueba es que el backend pida lo correcto según el método, y que la evidencia
y el resultado del paso salgan bien.
"""
import pytest

from src.domain import study_lesson as sl
from src.domain.ports.lesson_generator import Lesson, LessonRequest
from src.domain.services.teaching_policy import LessonVariant
from src.domain.services.tutor_policy import TutorPolicy
from src.domain.value_objects.question import Difficulty, QuizQuestion
from src.infrastructure.ia.base_chat_analyst import BaseChatAnalyst
from tests.api.test_metodos_de_estudio_e2e import entorno, _ruta  # noqa: F401
from tests.api.test_preguntas_abiertas_e2e import IDEA_1, IDEA_2, _abierta, _auth, _cerrada, _respuestas

PASOS = ["Plantear 2x + 3 = 11", "Restar 3: 2x = 8", "Dividir entre 2: x = 4", "Comprobar: 2·4 + 3 = 11"]


def _leccion(req):
    """Lo que el backend pidió, redactado tal cual: tipos por posición, repaso y pasos."""
    tipos = req.check_kinds or ("choice",) * len(req.check_difficulties)
    check = [
        _abierta(f"Explica {req.concept} {k}", d, req.concept) if t == "open" else _cerrada(f"¿{req.concept} {k}?", d, req.concept, k)
        for k, (d, t) in enumerate(zip(req.check_difficulties, tipos))
    ]
    if req.review_concept:
        repaso = QuizQuestion(
            text=f"Repaso de {req.review_concept} ⟨B⟩", options={l: l for l in "ABCD"}, correct_answer="B",
            difficulty=Difficulty.MEDIUM, concept_tags=(req.review_concept,),
            position=req.review_position, concept_title=req.review_concept_title,
        )
        check = [repaso, *check] if req.review_position == "before" else [*check, repaso]
    return Lesson(
        explanation=f"Explicación de {req.concept_title}. " * 4, example="Enunciado del ejemplo.",
        example_summary="ejemplo", check=tuple(check), worked_steps=tuple(PASOS) if req.worked_example else (),
    )


@pytest.fixture
def clase(entorno):  # noqa: F811
    c, modelo = entorno

    async def generar(req):
        modelo.lecciones.append(req)
        return _leccion(req)

    modelo.generate_lesson = generar
    return c, modelo


def _superar_paso(c, h, ruta_id, fallar_repaso=False):
    """Responde bien hasta que la clase pasa a otro concepto. Devuelve la última respuesta."""
    antes = c.get(f"/api/v1/learning/paths/{ruta_id}", headers=h).json()["teaching"]["concept"]
    for _ in range(4):
        check = c.post(f"/api/v1/learning/paths/{ruta_id}/lesson", headers=h).json()["check"]
        respuestas = _respuestas(check)
        if fallar_repaso:
            for q in check["questions"]:
                if q["concept_title"]:
                    respuestas[str(q["index"])] = next(k for k in q["options"] if k != respuestas[str(q["index"])])
        r = c.post(f"/api/v1/learning/paths/{ruta_id}/check", headers=h, json={"quiz_id": check["id"], "answers": respuestas})
        if c.get(f"/api/v1/learning/paths/{ruta_id}", headers=h).json()["teaching"]["concept"] != antes:
            return r.json()
    raise AssertionError("el paso no se superó")


def test_recuerdo_activo_pregunta_antes_por_lo_ultimo_superado(clase):
    c, modelo = clase
    h = _auth(c)
    ruta = _ruta(c, h)
    c.post(f"/api/v1/learning/paths/{ruta['id']}/lesson", headers=h, json={"study_method": "active_recall"})
    assert modelo.lecciones[-1].review_concept == ""  # primer concepto: no hay qué recuperar
    superado = c.get(f"/api/v1/learning/paths/{ruta['id']}", headers=h).json()["teaching"]["concept"]
    _superar_paso(c, h, ruta["id"])

    check = c.post(f"/api/v1/learning/paths/{ruta['id']}/lesson", headers=h).json()["check"]
    primera = check["questions"][0]
    assert primera["position"] == "before" and primera["concept_title"]
    assert modelo.lecciones[-1].review_concept == superado
    assert all(q["position"] == "after" and q["concept_title"] is None for q in check["questions"][1:])


def test_el_repaso_es_evidencia_de_su_concepto_y_no_decide_el_paso(clase):
    c, modelo = clase
    h = _auth(c)
    ruta = _ruta(c, h)
    c.post(f"/api/v1/learning/paths/{ruta['id']}/lesson", headers=h, json={"study_method": "active_recall"})
    superado = c.get(f"/api/v1/learning/paths/{ruta['id']}", headers=h).json()["teaching"]["concept"]
    _superar_paso(c, h, ruta["id"])

    r = _superar_paso(c, h, ruta["id"], fallar_repaso=True)
    repaso = next(q for q in r["questions"] if q["concept_title"])
    assert repaso["is_correct"] is False
    assert r["outcome"] == "understood"  # el fallo del repaso no tumba el paso actual
    perfil = c.get("/api/v1/learning/me/profile", headers=h).json()
    assert any(x["concept_key"] == superado for x in perfil["mastery_by_concept"])


def test_explicalo_tu_cierra_con_una_abierta(clase):
    c, modelo = clase
    h = _auth(c)
    ruta = _ruta(c, h)
    check = c.post(f"/api/v1/learning/paths/{ruta['id']}/lesson", headers=h, json={"study_method": "feynman"}).json()["check"]
    assert modelo.lecciones[-1].explain_it is True
    assert check["questions"][-1]["kind"] == "open"


def test_preguntarse_el_porque_lo_pide_en_el_prompt(clase):
    c, modelo = clase
    h = _auth(c)
    ruta = _ruta(c, h)
    c.post(f"/api/v1/learning/paths/{ruta['id']}/lesson", headers=h, json={"study_method": "elaboration"})
    req = modelo.lecciones[-1]
    assert req.why_guided is True
    assert "¿Por qué…?" in TutorPolicy().teaching_lesson(req).system


def test_ejemplos_resueltos_completo_la_primera_vez_y_desvanecido_despues(clase):
    c, _ = clase
    h = _auth(c)
    ruta = _ruta(c, h)
    r = c.post(f"/api/v1/learning/paths/{ruta['id']}/lesson", headers=h, json={"study_method": "worked_examples"}).json()
    assert [s["hidden"] for s in r["worked_example"]["steps"]] == [False] * 4
    assert c.post(f"/api/v1/learning/paths/{ruta['id']}/lesson", headers=h).json()["worked_example"] == r["worked_example"]

    concepto = r["path"]["teaching"]["concept"]
    c.post(f"/api/v1/learning/paths/{ruta['id']}/check", headers=h,
           json={"quiz_id": r["check"]["id"], "answers": _respuestas(r["check"])})
    siguiente = c.post(f"/api/v1/learning/paths/{ruta['id']}/lesson", headers=h).json()
    ocultos = [s["hidden"] for s in siguiente["worked_example"]["steps"]]
    if siguiente["path"]["teaching"]["concept"] == concepto:
        assert ocultos == [False, False, False, True]  # afianzar el mismo: un paso menos a la vista
    else:
        assert ocultos == [False] * 4  # concepto nuevo: el ejemplo vuelve a estar completo


def test_sin_metodo_la_leccion_es_la_de_siempre(clase):
    c, modelo = clase
    h = _auth(c)
    ruta = _ruta(c, h)
    r = c.post(f"/api/v1/learning/paths/{ruta['id']}/lesson", headers=h).json()
    req = modelo.lecciones[-1]
    assert (req.study_method, req.review_concept, req.explain_it, req.why_guided, req.worked_example) == (None, "", False, False, False)
    assert r["worked_example"] is None


# --- Dominio y redacción ---------------------------------------------------------------


def test_plan_por_metodo():
    base = dict(current="c", tier="basico", understood_streak=0)
    assert sl.plan_for("active_recall", passed=["a", "b"], **base).review_concept == "b"
    inter = sl.plan_for("interleaving", passed=["a"], **base)
    assert inter.method == "active_recall" and inter.note  # con menos de dos, recuerdo activo
    elegido = sl.plan_for("interleaving", passed=["a", "b", "c"], effective_mastery={"a": 0.9, "b": 0.2}, **base)
    assert (elegido.review_concept, elegido.review_position) == ("b", "after")  # el más olvidado
    assert sl.plan_for("worked_examples", passed=[], current="c", tier="avanzado", understood_streak=0).method is None
    assert sl.plan_for("worked_examples", passed=[], current="c", tier="basico", understood_streak=2).worked_hidden == 2
    assert sl.plan_for(None, passed=[], **base) == sl.MethodPlan()


@pytest.mark.parametrize("ocultos, esperado", [(0, [False] * 4), (1, [False, False, False, True]), (9, [False, True, True, True])])
def test_el_desvanecimiento_nunca_oculta_el_primer_paso(ocultos, esperado):
    assert [h for _, h in sl.fade(PASOS, ocultos)] == esperado


def _req(**kw):
    base = dict(topic_label="Ecuaciones", concept="despejar", concept_title="Despejar",
                variant=LessonVariant.INTRODUCE, check_difficulties=(Difficulty.EASY, Difficulty.MEDIUM))
    return LessonRequest(**{**base, **kw})


def test_el_parser_lee_repaso_y_pasos_y_tolera_que_falten():
    datos = {
        "explanation": "x" * 60, "example": "Resuelve 2x + 3 = 11", "example_summary": "e",
        "check": [{"text": "¿a?", "options": {"A": "1", "B": "2", "C": "3"}, "correct_answer": "A"}] * 2,
        "review_question": {"text": "¿Qué es una fracción?", "options": {"A": "x", "B": "y", "C": "z"}, "correct_answer": "B"},
        "worked_example": {"steps": PASOS},
    }
    leccion = BaseChatAnalyst._lesson_desde(datos, _req(review_concept="fraccion", review_concept_title="Fracción",
                                                       review_position="before", worked_example=True))
    assert leccion.check[0].position == "before" and leccion.check[0].concept_tags == ("fraccion",)
    assert leccion.check[0].concept_title == "Fracción" and leccion.worked_steps == tuple(PASOS)

    sin_extras = {k: v for k, v in datos.items() if k not in ("review_question", "worked_example")}
    leccion = BaseChatAnalyst._lesson_desde(sin_extras, _req(review_concept="fraccion", worked_example=True))
    assert len(leccion.check) == 2 and leccion.worked_steps == ()


def test_el_prompt_pide_lo_del_metodo():
    sistema = TutorPolicy().teaching_lesson(_req(review_concept="f", review_concept_title="Fracción", worked_example=True, explain_it=True)).system
    assert "review_question" in sistema and "«Fracción»" in sistema
    assert "worked_example" in sistema and "Explica con tus palabras" in sistema
    assert "review_question" not in TutorPolicy().teaching_lesson(_req()).system
