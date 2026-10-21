"""Imágenes con licencia de Wikimedia para objetos reales (ADR-048, fase 2).

El modelo no pone URLs: escribe una marca `[[imagen: objeto]]` y el servidor busca
una foto con licencia libre y la atribuye, o quita la marca. Una URL que no sea de
Wikimedia, una licencia no libre o una imagen que la moderación rechace no llegan.
"""
from src.domain.services.learner_context import LearnerContext
from src.domain.services.cognitive_style import CognitiveStyle
from src.domain.services.tutor_policy import TutorPolicy
from src.domain.services.visuals import (
    IMAGE_INSTRUCTION,
    LicensedImage,
    image_is_safe,
    image_requests,
    is_free_license,
    place_images,
)

VOLCAN = LicensedImage(
    url="https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Villarrica.jpg/800px-Villarrica.jpg",
    page_url="https://commons.wikimedia.org/wiki/File:Villarrica.jpg",
    title="Volcán Villarrica",
    author="Ana Pérez",
    license="CC BY-SA 4.0",
    license_url="https://creativecommons.org/licenses/by-sa/4.0",
)

TEXTO = "Un volcán es una abertura de la corteza.\n\n[[imagen: volcán]]\n\nPor ahí sale el magma."


def test_la_marca_se_lee_y_solo_vale_una():
    assert image_requests(TEXTO) == ["volcán"]
    assert image_requests(TEXTO + "\n[[imagen: lava]]") == ["volcán"]
    assert image_requests("sin imágenes") == []
    assert image_requests("en mitad [[imagen: volcán]] de una frase") == [], "solo en línea propia"


def test_con_imagen_la_marca_se_cambia_por_la_foto_y_su_atribucion():
    texto, visuales = place_images(TEXTO, {"volcán": VOLCAN})

    assert "[[imagen" not in texto
    assert f"![Volcán Villarrica]({VOLCAN.url})" in texto
    assert "Ana Pérez" in texto and "CC BY-SA 4.0" in texto and "Wikimedia Commons" in texto
    assert visuales == [VOLCAN.to_dict()] and visuales[0]["kind"] == "image"


def test_sin_imagen_la_marca_se_quita_sin_dejar_huecos():
    texto, visuales = place_images(TEXTO, {})

    assert texto == "Un volcán es una abertura de la corteza.\n\nPor ahí sale el magma."
    assert visuales == []


def test_las_miniaturas_de_wikimedia_llegan():
    """Medido contra la API real: las miniaturas vienen de thumb.wikimedia.org."""
    mini = LicensedImage(**{**VOLCAN.__dict__, "url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/ab/V.jpg/800px-V.jpg"})

    _, visuales = place_images(TEXTO, {"volcán": mini})

    assert visuales and visuales[0]["url"] == mini.url


def test_una_url_que_no_es_de_wikimedia_no_llega():
    falsa = LicensedImage(**{**VOLCAN.__dict__, "url": "https://evil.example/x.jpg"})

    texto, visuales = place_images(TEXTO, {"volcán": falsa})

    assert "evil.example" not in texto and visuales == []


def test_los_textos_de_la_atribucion_no_rompen_el_markdown():
    rara = LicensedImage(**{**VOLCAN.__dict__, "title": "Volcán](javascript:x)", "author": "<b>[Ana]</b>"})

    texto, _ = place_images(TEXTO, {"volcán": rara})

    assert "javascript:x)" not in texto.split(VOLCAN.url)[0]
    assert "<b>" not in texto and "[Ana]" not in texto


def test_solo_licencias_libres():
    for libre in ("CC0", "CC BY 4.0", "CC BY-SA 3.0", "Public domain", "PD", "Dominio público"):
        assert is_free_license(libre), libre
    for no in ("CC BY-NC 4.0", "CC BY-ND 2.0", "Fair use", "", "All rights reserved"):
        assert not is_free_license(no), no


def test_la_moderacion_rechaza_lo_sexual_o_violento():
    assert image_is_safe({"sexual": 0.01, "violence/graphic": 0.02})
    assert not image_is_safe({"sexual": 0.6})
    assert not image_is_safe({"sexual/minors": 0.05})
    assert not image_is_safe({"violence/graphic": 0.7})


def test_la_instruccion_solo_va_con_imagenes_activas_y_estilo_visual():
    policy = TutorPolicy()

    def system(**kw):
        return policy.answer_question("", "¿Cómo es un volcán?", None, learner=LearnerContext(**kw)).system

    assert IMAGE_INSTRUCTION in system(style=CognitiveStyle.VISUAL, images=True)
    assert IMAGE_INSTRUCTION not in system(style=CognitiveStyle.VISUAL)
    assert IMAGE_INSTRUCTION not in system(style=CognitiveStyle.SIMPLE, images=True)


def test_en_la_clase_la_instruccion_va_en_la_explicacion():
    from src.domain.aggregates.learning_path import LessonVariant
    from src.domain.ports.lesson_generator import LessonRequest
    from src.domain.value_objects.question import Difficulty

    def req(**kw):
        return LessonRequest(
            topic_label="Volcanes", concept="volcan", concept_title="Volcanes", variant=LessonVariant.INTRODUCE,
            check_difficulties=(Difficulty.EASY, Difficulty.MEDIUM), style=CognitiveStyle.VISUAL, **kw,
        )

    assert "[[imagen:" in TutorPolicy().teaching_lesson(req(images=True)).system
    assert "[[imagen:" not in TutorPolicy().teaching_lesson(req()).system
