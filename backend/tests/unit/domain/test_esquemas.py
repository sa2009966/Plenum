"""El tutor puede dibujar un esquema, y solo llegan los que se pueden pintar (ADR-048).

El estilo «Con esquemas y dibujos» se ofrecía al estudiante y el tutor solo describía
el esquema con palabras. Ahora lo dibuja en Mermaid; lo que no sea un esquema de
clase (directivas, `click`, HTML, otros tipos, demasiado grande) no llega al navegador.
"""
import pytest

from src.domain.services.cognitive_style import CognitiveStyle
from src.domain.services.speakable import AVISO_ESQUEMA, speakable_text
from src.domain.services.tutor_policy import TutorPolicy
from src.domain.services.learner_context import LearnerContext
from src.domain.services.visuals import (
    DIAGRAM_INSTRUCTION,
    MAX_DIAGRAM_CHARS,
    asks_for_diagram,
    extract_diagrams,
    wants_diagram,
)

FLUJO = 'flowchart TD\n  A["Agua"] --> B["Vapor"]\n  B --> C["Nube"]'


def _con(fuente: str) -> str:
    return f"El ciclo del agua tiene tres pasos.\n\n```mermaid\n{fuente}\n```\n\nCada paso…"


def test_un_esquema_valido_se_queda_en_su_sitio_y_se_anuncia():
    texto, esquemas = extract_diagrams(_con(FLUJO))
    assert f"```mermaid\n{FLUJO}\n```" in texto
    assert [e.to_dict() for e in esquemas] == [{"kind": "mermaid", "diagram": "flowchart", "source": FLUJO}]


@pytest.mark.parametrize(
    "fuente",
    [
        '%%{init: {"securityLevel": "loose"}}%%\n' + FLUJO,  # directiva de configuración
        FLUJO + '\n  click A "https://malo.example"',  # enlace al hacer clic
        FLUJO + "\n  click A call alerta()",  # callback
        'flowchart TD\n  A["<img src=x onerror=alert(1)>"]',  # HTML
        FLUJO + "\n  style A fill:#f00",  # estilos
        "gantt\n  title Plan",  # tipo que no explica nada en una clase
        "pie\n  \"a\": 1",
        "flowchart TD\n" + "\n".join(f"  N{i} --> N{i + 1}" for i in range(60)),  # demasiadas líneas
        "flowchart TD\n  A[\"" + "x" * MAX_DIAGRAM_CHARS + "\"]",  # demasiado largo
        "",
    ],
)
def test_lo_que_no_es_un_esquema_de_clase_se_quita(fuente):
    texto, esquemas = extract_diagrams(_con(fuente))
    assert esquemas == []
    assert "```mermaid" not in texto
    assert texto.startswith("El ciclo del agua") and texto.endswith("Cada paso…")


def test_un_salto_de_linea_html_si_se_admite():
    fuente = 'flowchart TD\n  A["Agua<br>líquida"] --> B["Vapor"]'
    assert extract_diagrams(_con(fuente))[1]


def test_solo_uno_por_respuesta_y_sin_cerrar_no_vale():
    dos = _con(FLUJO) + "\n\n```mermaid\nmindmap\n  root((Agua))\n```"
    texto, esquemas = extract_diagrams(dos)
    assert len(esquemas) == 1 and texto.count("```mermaid") == 1

    cortado = "Mira:\n```mermaid\nflowchart TD\n  A --> B"
    texto, esquemas = extract_diagrams(cortado)
    assert esquemas == [] and texto == "Mira:"


def test_el_resto_del_codigo_no_se_toca():
    texto = "Así:\n```python\nprint('hola')\n```"
    assert extract_diagrams(texto) == (texto, [])


@pytest.mark.parametrize(
    "pregunta, pide",
    [
        ("¿me haces un esquema de la fotosíntesis?", True),
        ("dibújame el ciclo del agua", True),
        ("hazme un mapa conceptual", True),
        ("explícalo con un diagrama de flujo", True),
        ("¿qué es la fotosíntesis?", False),
        ("resuelve 2x + 3 = 7", False),
    ],
)
def test_pedirlo_con_palabras(pregunta, pide):
    assert asks_for_diagram(pregunta) is pide


def test_se_permite_por_estilo_visual_o_por_pedirlo():
    assert wants_diagram(CognitiveStyle.VISUAL)
    assert wants_diagram(CognitiveStyle.SIMPLE, "hazme un esquema")
    assert not wants_diagram(CognitiveStyle.SIMPLE, "¿qué es un átomo?")
    assert not wants_diagram(None)


def test_el_prompt_lo_pide_solo_cuando_toca():
    politica = TutorPolicy()

    def sistema(pregunta, estilo=None):
        return politica.answer_question("", pregunta, None, learner=LearnerContext(style=estilo)).system

    assert DIAGRAM_INSTRUCTION in sistema("¿qué es la fotosíntesis?", CognitiveStyle.VISUAL)
    assert DIAGRAM_INSTRUCTION in sistema("hazme un esquema de la fotosíntesis")
    assert DIAGRAM_INSTRUCTION not in sistema("¿qué es la fotosíntesis?")


def test_la_voz_dice_esquema_no_codigo():
    voz = speakable_text(_con(FLUJO))
    assert AVISO_ESQUEMA in voz and "flowchart" not in voz and "código" not in voz
