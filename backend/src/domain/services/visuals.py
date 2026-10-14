"""Esquemas en las explicaciones del tutor (ADR-048).

El estilo «Con esquemas y dibujos» solo pedía al modelo *describir* un esquema con
palabras. Ahora puede dibujarlo: escribe un bloque ```mermaid dentro de la
respuesta y el cliente lo pinta. Se eligió texto y no imagen generada porque un
diagrama en texto tiene las etiquetas exactas, llega con el streaming y se puede
validar; una imagen generada se inventa rótulos y flechas, y el estudiante se fía
de lo que ve.

Aquí vive lo que se decide (cuándo se pide un esquema) y lo que se garantiza al
cliente (qué esquemas llegan). El modelo solo redacta el bloque.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from src.domain.services.cognitive_style import CognitiveStyle

#: Los tipos de Mermaid que sirven para explicar: procesos, secuencias, estados,
#: jerarquías y cronologías. Otros (gantt, pie, quadrant…) no aportan a una clase.
ALLOWED_DIAGRAMS: tuple[str, ...] = (
    "flowchart",
    "graph",
    "sequenceDiagram",
    "stateDiagram-v2",
    "stateDiagram",
    "mindmap",
    "timeline",
    "classDiagram",
)
#: Un esquema que cabe en la pantalla de un móvil y se entiende de un vistazo.
MAX_DIAGRAM_CHARS = 2_000
MAX_DIAGRAM_LINES = 40
#: Uno por respuesta: dos esquemas compiten por la atención del estudiante.
MAX_DIAGRAMS = 1

DIAGRAM_INSTRUCTION = (
    " Si un esquema ayuda a entenderlo, dibuja UNO en un bloque de código ```mermaid "
    "(flowchart TD, sequenceDiagram, stateDiagram-v2, mindmap o timeline): como mucho "
    "12 nodos, etiquetas cortas en español entre comillas, sin estilos, sin enlaces ni "
    "directivas %%. Explícalo en el texto: el esquema acompaña a la explicación, no la "
    "sustituye. Si el tema no tiene estructura que dibujar, no lo fuerces."
)

_PIDE_ESQUEMA = re.compile(
    r"\b(esquema|esquematiza\w*|diagrama|dib[uú]j\w*|mapa\s+(?:conceptual|mental)|"
    r"flujograma|diagrama\s+de\s+flujo|gr[aá]fic(?:o|amente)|visualmente|ilustra\w*)\b",
    re.I,
)
_BLOQUE = re.compile(r"```[ \t]*mermaid[ \t]*\n(.*?)(?:\n```|\Z)", re.S | re.I)
#: Lo que Mermaid admite pero un esquema de clase nunca necesita, y que abre la
#: puerta a ejecutar o cargar algo en el navegador del estudiante: directivas de
#: configuración, `click` con callbacks o enlaces, estilos y HTML.
_PROHIBIDO = re.compile(
    r"%%|\bclick\b|\bcall\b|\bhref\b|javascript:|<(?!br\s*/?>)[a-z/!]|\bstyle\b|"
    r"\bclassDef\b|\blinkStyle\b|@\{",
    re.I,
)


def asks_for_diagram(question: str) -> bool:
    """El estudiante pide un esquema con sus palabras ("hazme un esquema", "dibújalo")."""
    return bool(_PIDE_ESQUEMA.search(question or ""))


def wants_diagram(style: CognitiveStyle | None, question: str = "") -> bool:
    """Se le permite dibujar si su estilo es visual o si lo pidió en este mensaje."""
    return style == CognitiveStyle.VISUAL or asks_for_diagram(question)


@dataclass(frozen=True)
class Diagram:
    kind: str  # "mermaid"
    diagram: str  # el tipo: flowchart, sequenceDiagram…
    source: str

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "diagram": self.diagram, "source": self.source}


def _tipo(fuente: str) -> str | None:
    primera = next((ln.strip() for ln in fuente.splitlines() if ln.strip()), "")
    palabra = primera.split()[0] if primera else ""
    return palabra if palabra in ALLOWED_DIAGRAMS else None


def _valido(fuente: str) -> str | None:
    """El tipo del esquema si se puede entregar; None si hay que quitarlo."""
    if not fuente.strip() or len(fuente) > MAX_DIAGRAM_CHARS:
        return None
    if len(fuente.splitlines()) > MAX_DIAGRAM_LINES or _PROHIBIDO.search(fuente):
        return None
    return _tipo(fuente)


def extract_diagrams(content: str) -> tuple[str, list[Diagram]]:
    """Separa lo que llega al estudiante de lo que no: `(texto final, esquemas)`.

    Los esquemas válidos se quedan en su sitio dentro del markdown (el cliente
    los pinta donde el modelo los puso) y se listan para el envelope. Los que no
    pasan —tipo no permitido, directivas, HTML, demasiado grandes, más de uno o
    sin cerrar— se quitan: es mejor una explicación sin dibujo que un dibujo roto
    o inseguro.
    """
    if not content or "```" not in content:
        return content, []
    esquemas: list[Diagram] = []

    def _decide(m: re.Match) -> str:
        fuente = m.group(1).strip("\n")
        cerrado = m.group(0).rstrip().endswith("```")
        tipo = _valido(fuente) if cerrado else None
        if tipo is None or len(esquemas) >= MAX_DIAGRAMS:
            return ""
        esquemas.append(Diagram("mermaid", tipo, fuente))
        return f"```mermaid\n{fuente}\n```"

    limpio = _BLOQUE.sub(_decide, content)
    # Quitar un bloque deja líneas en blanco de más.
    limpio = re.sub(r"\n{3,}", "\n\n", limpio).strip()
    return limpio, esquemas
