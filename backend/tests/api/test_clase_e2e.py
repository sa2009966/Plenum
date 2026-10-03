"""La clase de punta a punta por HTTP (ADR-028).

Nivelación → ruta → explicación → comprobación → evidencia → mastery → siguiente
paso, con repositorios y projector reales del modo memoria. Solo el modelo es un
doble (es una dependencia externa): genera contenido determinista y deja
anotado qué se le pidió, para comprobar que las DECISIONES las tomó el backend.

Cada paso es una petición HTTP nueva y el repositorio en memoria guarda copias:
la clase continúa porque el estado se persistió, no porque un objeto siguiera vivo.
"""
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.application.services.quiz_service import QuizService
from src.application.services.teaching_service import TeachingService
from src.application.services.topic_catalog import TopicCatalog
from src.domain.ports.lesson_generator import Lesson, SyllabusItem
from src.domain.value_objects.question import Quiz, QuizQuestion
from src.interfaces.api import dependencies as deps
from src.main import app
from tests.conftest import clear_dependency_caches

LETRAS = "ABCD"


class ModeloFalso:
    """Redacta; no decide. Anota cada petición para verificar qué pidió el backend."""

    def __init__(self):
        self.lecciones = []
        self.temarios = []

    async def generate_diagnostic(self, plan) -> Quiz:
        preguntas, i = [], 0
        for peldano in plan.rungs:
            for n in range(peldano.items):
                c = LETRAS[i % 4]
                i += 1
                preguntas.append(QuizQuestion(
                    text=f"diag #{i} ⟨{c}⟩", options={l: l for l in LETRAS}, correct_answer=c,
                    difficulty=peldano.difficulty, concept_tags=(peldano.concepts[n % len(peldano.concepts)],)))
        return Quiz(questions=preguntas)

    async def generate_lesson(self, req) -> Lesson:
        self.lecciones.append(req)
        n = len(self.lecciones)
        return Lesson(
            explanation=f"Explicación {n} de {req.concept_title} ({req.variant.value}). " * 3,
            example=f"Ejemplo {n} resuelto paso a paso.",
            example_summary=f"ejemplo {n}",
            check=tuple(
                QuizQuestion(text=f"¿{req.concept} {n}.{k}? ⟨{c}⟩", options={l: l for l in LETRAS},
                             correct_answer=c, difficulty=d, concept_tags=(req.concept,))
                for k, (c, d) in enumerate(zip("AB", req.check_difficulties))
            ),
        )

    async def propose_next_topics(self, label, level):
        self.siguientes = getattr(self, "siguientes", 0) + 1
        return ["Programación orientada a objetos", "Estructuras de datos"]

    async def propose_syllabus(self, label, level, avoid=()):
        self.temarios.append(label)
        if avoid:
            # Tramo nuevo (ADR-037): repite uno ya visto para comprobar que se descarta.
            self.tramos = getattr(self, "tramos", []) + [(level, avoid)]
            return [SyllabusItem(avoid[0]), SyllabusItem(f"Patrones {level}"),
                    SyllabusItem(f"Diseño {level}", (f"Patrones {level}",))]
        return [SyllabusItem("Variables"), SyllabusItem("Bucles", ("Variables",))]


@pytest.fixture
def entorno():
    clear_dependency_caches()
    app.dependency_overrides.clear()
    modelo = ModeloFalso()

    def quiz_service():
        return QuizService(
            document_repository=deps.get_document_repo(), quiz_repository=deps.get_quiz_repo(),
            attempt_repository=deps.get_attempt_repo(), interaction_repository=deps.get_interaction_repo(),
            ia_analyst=modelo, event_bus=deps.get_event_bus(), profile_repository=deps.get_profile_repo(),
            session_repository=deps.get_session_repo(),
        )

    app.dependency_overrides[deps.get_quiz_service] = quiz_service
    app.dependency_overrides[deps.get_teaching_service] = lambda: TeachingService(
        path_repository=deps.get_learning_path_repo(), profile_repository=deps.get_profile_repo(),
        quiz_repository=deps.get_quiz_repo(), quiz_service=quiz_service(), lesson_generator=modelo,
        topic_catalog=TopicCatalog(), attempt_repository=deps.get_attempt_repo(),
    )
    with TestClient(app) as c:
        yield c, modelo
    app.dependency_overrides.clear()
    clear_dependency_caches()


def _auth(c):
    s = uuid4().hex[:8]
    email = f"clase_{s}@example.com"
    c.post("/api/v1/auth/register", json={"username": f"clase_{s}", "email": email, "password": "Clave123"})
    tok = c.post("/api/v1/auth/token", data={"username": email, "password": "Clave123"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _correctas(quiz):
    # Opciones barajadas en el servidor: se busca por el texto de la opción.
    return {
        str(q["index"]): next(k for k, v in q["options"].items() if v == q["text"].rsplit("⟨", 1)[1].rstrip("⟩"))
        for q in quiz["questions"]
    }


def _fallar(quiz):
    bien = _correctas(quiz)
    return {str(q["index"]): next(k for k in q["options"] if k != bien[str(q["index"])]) for q in quiz["questions"]}


def _nivelarse(c, h, tema, bien=True):
    q = c.post("/api/v1/quizzes/diagnostic", headers=h, json={"topic": tema}).json()
    r = c.post(f"/api/v1/quizzes/{q['id']}/attempts", headers=h,
               json={"answers": _correctas(q) if bien else _fallar(q)})
    return r.json()["placement"]


def _ruta(c, h, tema):
    r = c.post("/api/v1/learning/paths/from-topic", headers=h, json={"topic": tema})
    assert r.status_code == 200, r.text
    return r.json()


def _leccion(c, h, path_id):
    r = c.post(f"/api/v1/learning/paths/{path_id}/lesson", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _comprobar(c, h, path_id, quiz, respuestas):
    r = c.post(f"/api/v1/learning/paths/{path_id}/check", headers=h, json={"quiz_id": quiz["id"], "answers": respuestas})
    assert r.status_code == 200, r.text
    return r.json()


# --- Evaluación → ruta -------------------------------------------------------------------


def test_sin_nivelacion_la_ruta_espera_la_evaluacion_y_no_ensena(entorno):
    c, modelo = entorno
    h = _auth(c)

    ruta = _ruta(c, h, "fracciones")

    assert ruta["teaching"]["phase"] == "assessment"
    r = c.post(f"/api/v1/learning/paths/{ruta['id']}/lesson", headers=h)
    assert r.status_code == 409 and "nivelación" in r.json()["detail"]
    assert modelo.lecciones == [], "no se generó contenido sin evaluar"


def test_la_evaluacion_produce_una_ruta_desde_el_grafo(entorno):
    c, _ = entorno
    h = _auth(c)
    _nivelarse(c, h, "fracciones")

    ruta = _ruta(c, h, "fracciones")

    conceptos = [(m["concept"], m["kind"]) for m in ruta["modules"]]
    assert conceptos == [("numero entero", "prerequisite"), ("operaciones", "prerequisite"), ("fraccion", "content")]
    assert ruta["teaching"]["phase"] == "teaching"
    assert ruta["teaching"]["concept"] == "fraccion"


def test_pedir_la_ruta_dos_veces_no_crea_otra_ni_reinicia_la_clase(entorno):
    c, _ = entorno
    h = _auth(c)
    _nivelarse(c, h, "fracciones")
    r1 = _ruta(c, h, "fracciones")
    _leccion(c, h, r1["id"])

    r2 = _ruta(c, h, "Fracciones")

    assert r2["id"] == r1["id"] and r2["teaching"]["phase"] == "check"


def test_un_tema_fuera_del_grafo_usa_un_temario_validado(entorno):
    c, modelo = entorno
    h = _auth(c)
    _nivelarse(c, h, "python")

    ruta = _ruta(c, h, "python")

    assert [m["concept"] for m in ruta["modules"]] == ["variables", "bucles"]
    assert ruta["modules"][1]["prerequisites"] == ["variables"]
    assert ruta["teaching"]["concept"] == "variables" and modelo.temarios == ["Python"]


# --- Ruta → enseñanza → comprobación → evidencia → siguiente acción ---------------------


def test_la_leccion_entrega_explicacion_y_comprobacion_sin_respuestas(entorno):
    c, modelo = entorno
    h = _auth(c)
    _nivelarse(c, h, "fracciones")
    ruta = _ruta(c, h, "fracciones")

    paso = _leccion(c, h, ruta["id"])

    assert "Explicación 1" in paso["markdown"] and "**Ejemplo.**" in paso["markdown"]
    assert len(paso["check"]["questions"]) == 2 and "correct_answer" not in str(paso["check"])
    assert paso["path"]["teaching"]["phase"] == "check"
    assert [d.value for d in modelo.lecciones[0].check_difficulties] == ["easy", "medium"]


def test_una_segunda_peticion_recupera_el_mismo_paso_sin_generar_otro(entorno):
    c, modelo = entorno
    h = _auth(c)
    _nivelarse(c, h, "fracciones")
    ruta = _ruta(c, h, "fracciones")
    primero = _leccion(c, h, ruta["id"])

    otra = _leccion(c, h, ruta["id"])
    estado = c.get(f"/api/v1/learning/paths/{ruta['id']}", headers=h).json()

    assert otra["check"]["id"] == primero["check"]["id"] and otra["markdown"] == primero["markdown"]
    assert len(modelo.lecciones) == 1, "recuperar no vuelve a llamar al modelo"
    assert estado["teaching"]["pending_check_quiz_id"] == primero["check"]["id"]


def test_entender_deja_evidencia_en_el_perfil_y_avanza(entorno):
    c, _ = entorno
    h = _auth(c)
    _nivelarse(c, h, "fracciones")
    ruta = _ruta(c, h, "fracciones")
    antes = {x["concept_key"]: x for x in c.get("/api/v1/learning/me/profile", headers=h).json()["mastery_by_concept"]}

    paso = _leccion(c, h, ruta["id"])
    r = _comprobar(c, h, ruta["id"], paso["check"], _correctas(paso["check"]))

    despues = {x["concept_key"]: x for x in c.get("/api/v1/learning/me/profile", headers=h).json()["mastery_by_concept"]}
    assert r["outcome"] == "understood" and r["score"] == r["total_points"]
    assert despues["fraccion"]["attempts"] > antes["fraccion"]["attempts"], "la comprobación es evidencia"
    assert r["next"]["phase"] == "completed"
    assert r["path"]["teaching"]["phase"] == "completed"


def test_a_medias_da_un_ejemplo_nuevo_y_otra_comprobacion(entorno):
    c, modelo = entorno
    h = _auth(c)
    _nivelarse(c, h, "fracciones")
    ruta = _ruta(c, h, "fracciones")
    paso = _leccion(c, h, ruta["id"])
    medias = _correctas(paso["check"])
    medias["1"] = "D" if medias["1"] != "D" else "C"

    r = _comprobar(c, h, ruta["id"], paso["check"], medias)
    siguiente = _leccion(c, h, ruta["id"])

    assert r["outcome"] == "partial" and r["next"]["variant"] == "new_example"
    assert siguiente["check"]["id"] != paso["check"]["id"]
    assert modelo.lecciones[1].variant.value == "new_example"
    assert modelo.lecciones[1].avoid_example == "ejemplo 1", "se pide no repetir el ejemplo"


def test_no_entender_reformula_y_luego_remedia_la_base_y_vuelve(entorno):
    c, modelo = entorno
    h = _auth(c)
    _nivelarse(c, h, "fracciones")
    ruta = _ruta(c, h, "fracciones")

    paso = _leccion(c, h, ruta["id"])
    r1 = _comprobar(c, h, ruta["id"], paso["check"], _fallar(paso["check"]))
    assert r1["outcome"] == "not_understood" and r1["next"]["variant"] == "reformulate"

    paso = _leccion(c, h, ruta["id"])
    r2 = _comprobar(c, h, ruta["id"], paso["check"], _fallar(paso["check"]))
    assert r2["next"]["phase"] == "remediation"
    base = r2["next"]["concept"]
    assert base in ("numero entero", "operaciones")
    assert r2["path"]["teaching"]["return_to"] == "fraccion"

    paso = _leccion(c, h, ruta["id"])
    assert modelo.lecciones[-1].variant.value == "remediate"
    assert modelo.lecciones[-1].return_to_title == "Fracciones"
    r3 = _comprobar(c, h, ruta["id"], paso["check"], _correctas(paso["check"]))
    # La base vuelve a dominarse → se retoma el tema de partida.
    assert (r3["next"]["concept"], r3["next"]["variant"]) == ("fraccion", "resume")


def test_una_comprobacion_que_no_es_la_pendiente_es_409(entorno):
    c, _ = entorno
    h = _auth(c)
    _nivelarse(c, h, "fracciones")
    ruta = _ruta(c, h, "fracciones")
    paso = _leccion(c, h, ruta["id"])
    _comprobar(c, h, ruta["id"], paso["check"], _correctas(paso["check"]))

    repetida = c.post(f"/api/v1/learning/paths/{ruta['id']}/check", headers=h,
                      json={"quiz_id": paso["check"]["id"], "answers": _correctas(paso["check"])})
    assert repetida.status_code == 409


def test_la_clase_de_otro_estudiante_no_existe(entorno):
    c, _ = entorno
    h = _auth(c)
    _nivelarse(c, h, "fracciones")
    ruta = _ruta(c, h, "fracciones")

    otro = _auth(c)
    assert c.post(f"/api/v1/learning/paths/{ruta['id']}/lesson", headers=otro).status_code == 404


def test_ruta_completa_paso_a_paso_en_un_tema_con_dos_subtemas(entorno):
    """Avance al siguiente concepto hasta COMPLETED, cada paso en una petición nueva."""
    c, _ = entorno
    h = _auth(c)
    _nivelarse(c, h, "python")
    ruta = _ruta(c, h, "python")
    vistos = []
    for _ in range(6):
        paso = _leccion(c, h, ruta["id"])
        if paso["check"] is None:
            break
        vistos.append(paso["path"]["teaching"]["concept"])
        _comprobar(c, h, ruta["id"], paso["check"], _correctas(paso["check"]))

    final = c.get(f"/api/v1/learning/paths/{ruta['id']}", headers=h).json()
    assert vistos == ["variables", "bucles"]
    assert final["teaching"]["phase"] == "completed"
    assert set(final["teaching"]["passed_concepts"]) == {"variables", "bucles"}


def test_los_titulos_del_grafo_conservan_las_tildes(entorno):
    c, _ = entorno
    h = _auth(c)
    _nivelarse(c, h, "fracciones")

    titulos = [m["title"] for m in _ruta(c, h, "fracciones")["modules"]]

    assert titulos[0] == "Número entero", titulos


def test_una_ruta_completada_se_reabre_para_repasar_lo_olvidado(entorno):
    """Motor (ADR-032): el olvido ya bajaba el mastery efectivo; ahora la clase actúa."""
    import asyncio
    from datetime import datetime, timedelta, timezone

    c, modelo = entorno
    h = _auth(c)
    _nivelarse(c, h, "python")
    ruta = _ruta(c, h, "python")
    for _ in range(4):
        paso = _leccion(c, h, ruta["id"])
        if paso["check"] is None:
            break
        _comprobar(c, h, ruta["id"], paso["check"], _correctas(paso["check"]))
    assert _leccion(c, h, ruta["id"])["check"] is None, "ruta completada"

    # Pasan 60 días sin practicar "variables".
    uid = UUID(c.get("/api/v1/users/me", headers=h).json()["id"])
    repo = deps.get_profile_repo()
    perfil = asyncio.run(repo.find_by_student(uid))
    perfil.mastery_by_concept["variables"].last_practiced_at = datetime.now(timezone.utc) - timedelta(days=60)
    asyncio.run(repo.save(perfil))

    paso = _leccion(c, h, ruta["id"])

    assert paso["check"] is not None
    assert paso["path"]["teaching"]["concept"] == "variables"
    assert paso["path"]["teaching"]["variant"] == "review"
    assert "repasamos" in paso["path"]["teaching"]["reason"]
    assert modelo.lecciones[-1].variant.value == "review"



def _completar(c, h, ruta_id):
    for _ in range(8):
        paso = _leccion(c, h, ruta_id)
        if paso["check"] is None:
            return
        _comprobar(c, h, ruta_id, paso["check"], _correctas(paso["check"]))


def test_al_completar_un_tema_del_grafo_sugiere_lo_que_se_construye_encima(entorno):
    c, _ = entorno
    h = _auth(c)
    _nivelarse(c, h, "fracciones")  # nivel intermedio: hay margen para subir
    ruta = _ruta(c, h, "fracciones")
    _completar(c, h, ruta["id"])

    s = c.get(f"/api/v1/learning/paths/{ruta['id']}/next", headers=h).json()["suggestions"]

    assert s[0]["kind"] == "level_up" and s[0]["needs_placement"] is True
    avances = [x for x in s if x["kind"] == "advance"]
    assert {x["topic"] for x in avances} <= {"razon", "porcentaje", "fraccion algebraica"} and avances
    assert all(x["needs_placement"] for x in avances), "sin nivel guardado en esos temas"
    assert len(s) <= 3


def test_un_tema_fuera_del_grafo_pide_temas_al_modelo_una_sola_vez(entorno):
    c, modelo = entorno
    h = _auth(c)
    _nivelarse(c, h, "python")
    ruta = _ruta(c, h, "python")
    _completar(c, h, ruta["id"])

    s1 = c.get(f"/api/v1/learning/paths/{ruta['id']}/next", headers=h).json()["suggestions"]
    s2 = c.get(f"/api/v1/learning/paths/{ruta['id']}/next", headers=h).json()["suggestions"]

    relacionados = [x["label"] for x in s1 if x["kind"] == "related"]
    assert "Programación orientada a objetos" in relacionados
    assert s1 == s2 and modelo.siguientes == 1, "se guarda: no se vuelve a pedir"


def test_las_sugerencias_de_otra_persona_no_existen(entorno):
    c, _ = entorno
    h = _auth(c)
    _nivelarse(c, h, "fracciones")
    ruta = _ruta(c, h, "fracciones")

    assert c.get(f"/api/v1/learning/paths/{ruta['id']}/next", headers=_auth(c)).status_code == 404
