"""La lección de la clase trae su esquema validado y lo anuncia en `visuals` (ADR-048)."""
from dataclasses import replace

from tests.api.test_clase_e2e import _auth, _leccion, _nivelarse, _ruta, entorno  # noqa: F401

ESQUEMA = 'flowchart TD\n  A["Variable"] --> B["Valor"]'


def test_la_leccion_trae_su_esquema_y_quita_el_que_no_se_puede_pintar(entorno):  # noqa: F811
    c, modelo = entorno
    original = modelo.generate_lesson

    async def con_esquemas(req):
        leccion = await original(req)
        return replace(
            leccion,
            explanation=leccion.explanation
            + f"\n\n```mermaid\n{ESQUEMA}\n```\n\n```mermaid\n%%{{init: {{}}}}%%\nflowchart TD\n  A --> B\n```",
        )

    modelo.generate_lesson = con_esquemas
    h = _auth(c)
    _nivelarse(c, h, "python", bien=False)
    paso = _leccion(c, h, _ruta(c, h, "python")["id"])

    assert paso["visuals"] == [{"kind": "mermaid", "diagram": "flowchart", "source": ESQUEMA}]
    assert paso["markdown"].count("```mermaid") == 1 and "%%" not in paso["markdown"]


def test_con_estilo_visual_el_prompt_de_la_clase_pide_el_esquema():
    from src.domain.ports.lesson_generator import LessonRequest, LessonVariant
    from src.domain.services.cognitive_style import CognitiveStyle
    from src.domain.services.tutor_policy import TutorPolicy
    from src.domain.value_objects.question import Difficulty

    def sistema(estilo):
        req = LessonRequest(
            topic_label="Python", concept="variables", concept_title="Variables",
            variant=list(LessonVariant)[0], check_difficulties=(Difficulty.EASY, Difficulty.MEDIUM), style=estilo,
        )
        return TutorPolicy().teaching_lesson(req).system

    assert "```mermaid" in sistema(CognitiveStyle.VISUAL)
    assert "```mermaid" not in sistema(CognitiveStyle.SIMPLE)


def test_la_foto_pedida_en_la_leccion_llega_con_atribucion_o_se_quita(entorno):  # noqa: F811
    """ADR-048, fase 2: en la clase la foto va dentro del markdown de la explicación."""
    # El mismo módulo que usó el fixture: otro test puede haber recargado `dependencies`.
    from tests.api.test_clase_e2e import app, deps
    from tests.unit.application.test_imagenes_en_el_chat_y_la_clase import FOTO, Buscador

    c, modelo = entorno
    original = modelo.generate_lesson
    pedidas = []

    async def con_foto(req):
        pedidas.append(req.images)
        leccion = await original(req)
        return replace(leccion, explanation=leccion.explanation + "\n\n[[imagen: ojo humano]]\n\nFin.")

    modelo.generate_lesson = con_foto
    fabrica = app.dependency_overrides[deps.get_teaching_service]

    def con_buscador():
        servicio = fabrica()
        servicio._images = Buscador(FOTO)
        return servicio

    h = _auth(c)
    _nivelarse(c, h, "python", bien=False)
    ruta = _ruta(c, h, "python")["id"]
    app.dependency_overrides[deps.get_teaching_service] = con_buscador
    paso = _leccion(c, h, ruta)
    assert FOTO.url in paso["markdown"] and "[[imagen" not in paso["markdown"]
    assert "CC BY 4.0" in paso["markdown"] and pedidas[-1] is True

    # Recargar devuelve la misma lección, ya con la foto puesta (no se vuelve a buscar).
    app.dependency_overrides[deps.get_teaching_service] = fabrica
    assert _leccion(c, h, ruta)["markdown"] == paso["markdown"]


def test_sin_buscador_la_marca_de_la_leccion_se_quita(entorno):  # noqa: F811
    c, modelo = entorno
    original = modelo.generate_lesson

    async def con_foto(req):
        assert req.images is False
        leccion = await original(req)
        return replace(leccion, explanation=leccion.explanation + "\n\n[[imagen: ojo humano]]\n\nFin.")

    modelo.generate_lesson = con_foto
    h = _auth(c)
    _nivelarse(c, h, "python", bien=False)
    paso = _leccion(c, h, _ruta(c, h, "python")["id"])

    assert "[[imagen" not in paso["markdown"] and "Fin." in paso["markdown"]
