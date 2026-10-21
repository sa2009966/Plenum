"""Una pregunta de otro tema en clase se contesta corta y se vuelve a la clase.

Informe: durante las clases el tutor a veces desarrollaba demasiado preguntas ajenas
al tema. Solo se le pedía «responde en UNA frase», y gpt-4o-mini no siempre lo
cumplía (ADR-054, limitaciones). Ahora el servidor detecta la desviación, de forma
conservadora, y la respuesta lleva instrucción propia y un tope de longitud.
"""
import pytest

from src.domain.class_session import ClassSession, fuera_de_tema
from src.domain.services.learner_context import LearnerContext
from src.domain.services.tutor_policy import TutorPolicy

SESION = ClassSession(
    topic_label="Ecuaciones lineales",
    concept_title="Despejar la incógnita",
    concept="despejar",
    lesson_excerpt="Para despejar la x, lo que haces a un lado de la igualdad lo haces al otro.",
    key_points=("Lo que se hace a un lado se hace al otro", "El objetivo es dejar la x sola"),
    pending_check=("¿Cuánto vale x si 2x + 3 = 11?",),
)


@pytest.mark.parametrize(
    "pregunta",
    [
        "¿Quién ganó el mundial de fútbol de 2022?",
        "Cuéntame la historia del Imperio romano y sus emperadores",
        "¿Qué receta de pizza casera me recomiendas para la cena?",
    ],
)
def test_una_pregunta_de_otro_tema_se_detecta(pregunta):
    assert fuera_de_tema(pregunta, SESION) is True


@pytest.mark.parametrize(
    "pregunta",
    [
        "¿Por qué hay que restar en los dos lados?",
        "no entiendo nada de esto, estoy perdido",
        "¿Me lo explicas otra vez?",
        "¿Y si la incógnita está a la derecha?",
        "¿Cuánto vale x si 2x + 3 = 11?",
        "no entiendo por qué la historia de las ecuaciones empieza así",
        "Explícame cómo funcionan las ecuaciones con fracciones",
        "",
    ],
)
def test_lo_de_la_clase_las_dudas_y_lo_corto_no_se_toman_por_desvio(pregunta):
    """Ante la duda, es de la clase: confundir una duda real con un desvío es peor."""
    assert fuera_de_tema(pregunta, SESION) is False


def test_el_prompt_de_un_desvio_pide_dos_frases_y_volver_al_paso():
    from dataclasses import replace

    learner = LearnerContext(class_session=replace(SESION, off_topic=True))
    system = TutorPolicy().answer_question("", "¿Quién ganó el mundial?", None, learner=learner).system

    assert "NO es de la clase" in system and "dos frases" in system
    assert "«Despejar la incógnita»" in system.split("NO es de la clase")[1]


def test_una_duda_de_la_clase_no_lleva_la_orden_de_desvio():
    system = TutorPolicy().answer_question("", "¿Por qué?", None, learner=LearnerContext(class_session=SESION)).system

    assert "NO es de la clase" not in system


# --- La respuesta a un desvío tiene tope de longitud, no solo instrucción -----------------


def _analista(peticiones):
    import httpx

    from src.infrastructure.ia.base_chat_analyst import BaseChatAnalyst

    def responder(request):
        import json

        peticiones.append(json.loads(request.content))
        if json.loads(request.content).get("stream"):
            return httpx.Response(200, text='data: {"choices": [{"delta": {"content": "ok"}}]}\n\ndata: [DONE]\n\n')
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {}})

    a = BaseChatAnalyst.__new__(BaseChatAnalyst)
    a.model, a.api_url, a._headers, a._metrics, a._policy = "gpt-4o-mini", "http://x", {}, None, TutorPolicy()
    cliente = httpx.AsyncClient(transport=httpx.MockTransport(responder))

    async def get_cliente():
        return cliente

    a._get_client = get_cliente
    return a


@pytest.mark.asyncio
@pytest.mark.parametrize("en_streaming", [True, False])
async def test_un_desvio_tiene_tope_de_tokens_y_una_duda_no(en_streaming):
    from dataclasses import replace

    peticiones = []
    a = _analista(peticiones)
    for sesion in (replace(SESION, off_topic=True), SESION):
        learner = LearnerContext(class_session=sesion)
        if en_streaming:
            [t async for t in a.answer_question_stream("", "x", learner=learner)]
        else:
            await a.answer_question("", "x", learner=learner)

    desvio, duda = peticiones
    assert 0 < desvio["max_tokens"] <= 150
    assert "max_tokens" not in duda
