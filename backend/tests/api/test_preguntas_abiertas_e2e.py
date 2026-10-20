"""Preguntas abiertas de punta a punta por HTTP (ADR-053).

Nivelación solo con abiertas, práctica y clase con la mezcla elegida, corrección en
el servidor, resultado por pregunta y evidencia con crédito parcial. El modelo y el
juez son dobles (dependencias externas); lo que se comprueba es lo que decide el
backend: cuántas abiertas, dónde, cómo se corrigen y qué llega al cliente.
"""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.application.services.open_answer_service import OpenAnswerGradingService
from src.application.services.quiz_service import QuizService
from src.application.services.teaching_service import TeachingService
from src.application.services.topic_catalog import TopicCatalog
from src.domain.open_answers import RubricJudgement
from src.domain.ports.ia_analyst import IAAnalysisError
from src.domain.ports.lesson_generator import Lesson, SyllabusItem
from src.domain.value_objects.question import Quiz, QuizQuestion
from src.interfaces.api import dependencies as deps
from src.main import app
from tests.conftest import clear_dependency_caches

LETRAS = "ABCD"
IDEA_1, IDEA_2 = "la idea secreta uno", "la idea secreta dos"


def _abierta(texto, dificultad, concepto):
    return QuizQuestion(
        text=texto, options={}, correct_answer="", difficulty=dificultad, concept_tags=(concepto,),
        kind="open", key_points=(IDEA_1, IDEA_2), model_answer="Respuesta modelo de ejemplo para copiar.",
    )


def _cerrada(texto, dificultad, concepto, i):
    c = LETRAS[i % 4]
    return QuizQuestion(text=f"{texto} ⟨{c}⟩", options={l: l for l in LETRAS}, correct_answer=c,
                        difficulty=dificultad, concept_tags=(concepto,))


class Modelo:
    """Escribe exactamente lo que el plan pide: el backend decide tipos y cantidades."""

    def __init__(self):
        self.planes, self.lecciones = [], []

    async def generate_diagnostic(self, plan, **_):
        self.planes.append(plan)
        preguntas, i = [], 0
        for r in plan.rungs:
            for n in range(r.items):
                concepto = r.concepts[n % len(r.concepts)]
                i += 1
                if n < r.open_items:
                    preguntas.append(_abierta(f"Explica {concepto} #{i}", r.difficulty, concepto))
                else:
                    preguntas.append(_cerrada(f"¿{concepto} #{i}?", r.difficulty, concepto, i))
        return Quiz(questions=preguntas)

    async def generate_lesson(self, req):
        self.lecciones.append(req)
        tipos = req.check_kinds or ("choice",) * len(req.check_difficulties)
        return Lesson(
            explanation=f"Explicación de {req.concept_title}. " * 4,
            example="Ejemplo resuelto paso a paso.",
            example_summary="ejemplo",
            check=tuple(
                _abierta(f"Explica {req.concept} {k}", d, req.concept) if t == "open"
                else _cerrada(f"¿{req.concept} {k}?", d, req.concept, k)
                for k, (d, t) in enumerate(zip(req.check_difficulties, tipos))
            ),
        )

    async def propose_syllabus(self, label, level, avoid=()):
        return [SyllabusItem("Variables"), SyllabusItem("Bucles", ("Variables",))]

    async def propose_next_topics(self, label, level):
        return []


class Juez:
    """Cubre una idea si la respuesta la contiene. `caido` simula al proveedor sin servicio."""

    def __init__(self):
        self.caido = False
        self.llamadas = 0

    async def judge(self, question, answer):
        self.llamadas += 1
        if self.caido:
            raise IAAnalysisError("proveedor caído")
        cubiertas = tuple(p in answer for p in question.key_points)
        return RubricJudgement(cubiertas, False, "Te falta una idea.", tuple(p if c else "" for p, c in zip(question.key_points, cubiertas)))


@pytest.fixture
def entorno():
    clear_dependency_caches()
    app.dependency_overrides.clear()
    modelo, juez = Modelo(), Juez()

    def quiz_service():
        return QuizService(
            document_repository=deps.get_document_repo(), quiz_repository=deps.get_quiz_repo(),
            attempt_repository=deps.get_attempt_repo(), interaction_repository=deps.get_interaction_repo(),
            ia_analyst=modelo, event_bus=deps.get_event_bus(), profile_repository=deps.get_profile_repo(),
            session_repository=deps.get_session_repo(),
            open_answer_grader=OpenAnswerGradingService(juez), open_questions_enabled=True,
        )

    app.dependency_overrides[deps.get_quiz_service] = quiz_service
    app.dependency_overrides[deps.get_teaching_service] = lambda: TeachingService(
        path_repository=deps.get_learning_path_repo(), profile_repository=deps.get_profile_repo(),
        quiz_repository=deps.get_quiz_repo(), quiz_service=quiz_service(), lesson_generator=modelo,
        topic_catalog=TopicCatalog(), attempt_repository=deps.get_attempt_repo(),
    )
    with TestClient(app) as c:
        yield c, modelo, juez
    app.dependency_overrides.clear()
    clear_dependency_caches()


def _auth(c):
    s = uuid4().hex[:8]
    email = f"abiertas_{s}@example.com"
    c.post("/api/v1/auth/register", json={"username": f"ab_{s}", "email": email, "password": "Clave123"})
    tok = c.post("/api/v1/auth/token", data={"username": email, "password": "Clave123"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _respuestas(quiz, abierta="Lo explico con mis palabras: {i1} y también {i2}."):
    out = {}
    for q in quiz["questions"]:
        if q["kind"] == "open":
            out[str(q["index"])] = abierta.format(i1=IDEA_1, i2=IDEA_2)
        else:
            marca = q["text"].rsplit("⟨", 1)[1].rstrip("⟩")
            out[str(q["index"])] = next(k for k, v in q["options"].items() if v == marca)
    return out


def test_la_nivelacion_es_solo_de_abiertas_y_no_filtra_la_rubrica(entorno):
    c, _, _ = entorno
    h = _auth(c)
    r = c.post("/api/v1/quizzes/diagnostic", headers=h, json={"topic": "ecuaciones"})
    assert r.status_code == 201
    quiz = r.json()

    assert len(quiz["questions"]) == 4
    assert all(q["kind"] == "open" and q["options"] == {} and q["max_chars"] == 2000 for q in quiz["questions"])
    # Antes de contestar no viajan ni las ideas clave ni la respuesta modelo.
    assert IDEA_1 not in r.text and "Respuesta modelo" not in r.text


def test_corregir_abiertas_da_veredicto_feedback_y_las_ideas_despues(entorno):
    c, _, juez = entorno
    h = _auth(c)
    quiz = c.post("/api/v1/quizzes/diagnostic", headers=h, json={"topic": "ecuaciones"}).json()
    respuestas = _respuestas(quiz)
    respuestas["0"] = f"Solo sé esto: {IDEA_1}, nada más que eso."  # media respuesta

    r = c.post(f"/api/v1/quizzes/{quiz['id']}/attempts", headers=h, json={"answers": respuestas})
    assert r.status_code == 200, r.text
    preguntas = r.json()["questions"]
    primera = preguntas[0]
    assert primera["kind"] == "open" and primera["verdict"] == "partial" and primera["score"] == 0.5
    assert primera["is_correct"] is False and primera["feedback"]
    assert primera["key_points"] == [{"text": IDEA_1, "covered": True}, {"text": IDEA_2, "covered": False}]
    assert primera["model_answer"] and primera["correct_answer"] == ""
    assert all(q["verdict"] == "correct" and q["score"] == 1.0 for q in preguntas[1:])
    # 3,5 de 4 = 0,875 ≥ 0,75: el crédito parcial cuenta para el nivel.
    assert r.json()["score"] == 35 and r.json()["placement"]["passed"] is True
    assert juez.llamadas == 4


def test_una_copia_del_ejemplo_no_llega_al_juez(entorno):
    c, _, juez = entorno
    h = _auth(c)
    quiz = c.post("/api/v1/quizzes/diagnostic", headers=h, json={"topic": "ecuaciones"}).json()
    respuestas = _respuestas(quiz)
    respuestas["1"] = "Respuesta modelo de ejemplo para copiar."

    r = c.post(f"/api/v1/quizzes/{quiz['id']}/attempts", headers=h, json={"answers": respuestas}).json()
    assert r["questions"][1]["verdict"] == "copied" and r["questions"][1]["score"] == 0.0
    assert r["questions"][1]["feedback"]
    assert juez.llamadas == 3


def test_si_el_corrector_falla_no_se_guarda_nada_y_se_puede_reenviar(entorno):
    c, _, juez = entorno
    h = _auth(c)
    quiz = c.post("/api/v1/quizzes/diagnostic", headers=h, json={"topic": "ecuaciones"}).json()
    juez.caido = True
    r = c.post(f"/api/v1/quizzes/{quiz['id']}/attempts", headers=h, json={"answers": _respuestas(quiz)})
    assert r.status_code == 502 and r.json()["reason"] == "grader_unavailable"

    juez.caido = False
    # Una nivelación solo se responde una vez: si el fallo hubiera guardado algo, sería 409.
    assert c.post(f"/api/v1/quizzes/{quiz['id']}/attempts", headers=h, json={"answers": _respuestas(quiz)}).status_code == 200


def test_una_respuesta_demasiado_larga_es_422_con_su_indice(entorno):
    c, _, _ = entorno
    h = _auth(c)
    quiz = c.post("/api/v1/quizzes/diagnostic", headers=h, json={"topic": "ecuaciones"}).json()
    respuestas = _respuestas(quiz)
    respuestas["2"] = "x" * 2001
    r = c.post(f"/api/v1/quizzes/{quiz['id']}/attempts", headers=h, json={"answers": respuestas})
    assert r.status_code == 422 and r.json()["reason"] == "answer_too_long" and r.json()["index"] == 2


def test_la_practica_usa_la_mezcla_del_body(entorno):
    c, _, _ = entorno
    h = _auth(c)
    r = c.post("/api/v1/quizzes/practice", headers=h,
               json={"topic": "fracciones", "assessment": {"open_questions": 1, "choice_questions": 2}})
    assert r.status_code == 201, r.text
    tipos = [q["kind"] for q in r.json()["questions"]]
    assert sorted(tipos) == ["choice", "choice", "open"]


@pytest.mark.parametrize("mezcla", [{"open_questions": 0, "choice_questions": 0},
                                    {"open_questions": 11, "choice_questions": 0},
                                    {"open_questions": -1, "choice_questions": 3},
                                    {"open_questions": 8, "choice_questions": 8}])
def test_una_mezcla_vacia_negativa_o_enorme_es_422(entorno, mezcla):
    c, _, _ = entorno
    h = _auth(c)
    assert c.put("/api/v1/learning/me/preferences", headers=h, json={"assessment": mezcla}).status_code == 422
    assert c.post("/api/v1/quizzes/practice", headers=h, json={"topic": "fracciones", "assessment": mezcla}).status_code == 422


def test_las_preferencias_se_mezclan_y_no_se_pisan(entorno):
    c, _, _ = entorno
    h = _auth(c)
    inicial = c.get("/api/v1/learning/me/preferences", headers=h).json()
    assert inicial["assessment"] == {"open_questions": 3, "choice_questions": 3}

    r = c.put("/api/v1/learning/me/preferences", headers=h, json={"assessment": {"open_questions": 2, "choice_questions": 4}})
    assert r.json()["assessment"] == {"open_questions": 2, "choice_questions": 4}
    # Un PUT solo con el estilo no toca la mezcla, ni al revés.
    c.put("/api/v1/learning/me/preferences", headers=h, json={"explanation_style": "visual"})
    ahora = c.get("/api/v1/learning/me/preferences", headers=h).json()
    assert ahora == {"explanation_style": "visual", "assessment": {"open_questions": 2, "choice_questions": 4}}
    c.put("/api/v1/learning/me/preferences", headers=h, json={"assessment": {"open_questions": 1, "choice_questions": 1}})
    assert c.get("/api/v1/learning/me/preferences", headers=h).json()["explanation_style"] == "visual"


def test_la_clase_comprueba_con_la_mezcla_elegida_y_corrige_en_check(entorno):
    c, modelo, _ = entorno
    h = _auth(c)
    quiz = c.post("/api/v1/quizzes/diagnostic", headers=h, json={"topic": "programacion"}).json()
    c.post(f"/api/v1/quizzes/{quiz['id']}/attempts", headers=h, json={"answers": _respuestas(quiz)})
    ruta = c.post("/api/v1/learning/paths/from-topic", headers=h, json={"topic": "programacion"}).json()
    c.put("/api/v1/learning/me/preferences", headers=h, json={"assessment": {"open_questions": 2, "choice_questions": 2}})

    leccion = c.post(f"/api/v1/learning/paths/{ruta['id']}/lesson", headers=h)
    assert leccion.status_code == 200, leccion.text
    check = leccion.json()["check"]
    assert [q["kind"] for q in check["questions"]] == list(modelo.lecciones[-1].check_kinds)
    assert sorted(q["kind"] for q in check["questions"]) == ["choice", "choice", "open", "open"]

    r = c.post(f"/api/v1/learning/paths/{ruta['id']}/check", headers=h,
               json={"quiz_id": check["id"], "answers": _respuestas(check)})
    assert r.status_code == 200, r.text
    abiertas = [q for q in r.json()["questions"] if q["kind"] == "open"]
    assert abiertas and all(q["verdict"] == "correct" and q["key_points"] for q in abiertas)
    assert r.json()["outcome"] == "understood"


def test_el_body_de_la_clase_manda_sobre_la_preferencia(entorno):
    c, modelo, _ = entorno
    h = _auth(c)
    quiz = c.post("/api/v1/quizzes/diagnostic", headers=h, json={"topic": "programacion"}).json()
    c.post(f"/api/v1/quizzes/{quiz['id']}/attempts", headers=h, json={"answers": _respuestas(quiz)})
    ruta = c.post("/api/v1/learning/paths/from-topic", headers=h, json={"topic": "programacion"}).json()

    c.post(f"/api/v1/learning/paths/{ruta['id']}/lesson", headers=h,
           json={"assessment": {"open_questions": 0, "choice_questions": 5}})
    assert modelo.lecciones[-1].check_kinds == ("choice",) * 5


def test_con_las_abiertas_apagadas_todo_sigue_como_antes(entorno):
    c, modelo, _ = entorno
    app.dependency_overrides[deps.get_quiz_service] = lambda: QuizService(
        document_repository=deps.get_document_repo(), quiz_repository=deps.get_quiz_repo(),
        attempt_repository=deps.get_attempt_repo(), interaction_repository=deps.get_interaction_repo(),
        ia_analyst=modelo, event_bus=deps.get_event_bus(), profile_repository=deps.get_profile_repo(),
    )
    h = _auth(c)
    quiz = c.post("/api/v1/quizzes/diagnostic", headers=h, json={"topic": "ecuaciones"}).json()
    assert {q["kind"] for q in quiz["questions"]} == {"choice"} and len(quiz["questions"]) == 6
    practica = c.post("/api/v1/quizzes/practice", headers=h,
                      json={"topic": "fracciones", "num_questions": 4, "assessment": {"open_questions": 3, "choice_questions": 3}}).json()
    assert len(practica["questions"]) == 4 and {q["kind"] for q in practica["questions"]} == {"choice"}
