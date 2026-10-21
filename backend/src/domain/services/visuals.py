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


# --- Fase 2: imágenes con licencia de Wikimedia para objetos reales -----------------------
#
# Un esquema no enseña cómo es un volcán, un ojo o la Torre Eiffel: una foto sí. El
# modelo no pone URLs (se las inventaría): escribe una marca con el objeto y el servidor
# busca una foto con licencia libre, la modera y la atribuye. Si no hay, la marca se
# quita. Solo con estilo visual o si pidió un dibujo, como el esquema.

IMAGE_INSTRUCTION = (
    " Si ver una foto ayuda a reconocer un OBJETO REAL (un animal, una planta, un órgano, "
    "un lugar, un monumento, un instrumento o una máquina), escribe en una línea aparte "
    "[[imagen: nombre del objeto]]. Una como mucho, y nunca para ideas abstractas, "
    "procesos ni fórmulas: para eso está el esquema. La foto la busca el sistema."
)

_MARCA_IMAGEN = re.compile(r"^[ \t]*\[\[imagen:[ \t]*([^\]\n]{2,80}?)[ \t]*\]\][ \t]*$", re.M | re.I)
#: De aquí sale toda imagen que se entrega: lo demás no llega al navegador. Las
#: miniaturas vienen de `thumb.`; los originales, de `upload.` (medido contra la API).
_ORIGENES_IMAGENES = ("https://upload.wikimedia.org/", "https://thumb.wikimedia.org/")
_LICENCIAS_LIBRES = re.compile(r"^(cc0|cc[ -]by(?:[ -]sa)?(?:[ -]\d(?:\.\d)?)?|public domain|pd|dominio p[uú]blico)\b", re.I)
_LICENCIAS_NO_LIBRES = re.compile(r"\b(nc|nd)\b|non-?commercial|no ?deriv|fair use", re.I)
#: Umbrales de la moderación de imagen. Bajos a propósito: hay estudiantes menores.
_UMBRALES_IMAGEN = {"sexual": 0.2, "sexual/minors": 0.01, "violence/graphic": 0.4, "self-harm": 0.3}
_MAX_TEXTO_ATRIBUCION = 80


@dataclass(frozen=True)
class LicensedImage:
    url: str
    page_url: str
    title: str
    author: str
    license: str
    license_url: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": "image", "url": self.url, "page_url": self.page_url, "title": self.title,
            "author": self.author, "license": self.license, "license_url": self.license_url,
        }


def image_requests(content: str) -> list[str]:
    """Los objetos que el modelo quiere mostrar: como mucho uno, en su propia línea."""
    return [m.group(1).strip() for m in _MARCA_IMAGEN.finditer(content or "")][:1]


def is_free_license(name: str) -> bool:
    """CC0, CC BY, CC BY-SA o dominio público. Nada NC/ND: el uso es educativo pero no se sabe dónde."""
    nombre = (name or "").strip()
    return bool(_LICENCIAS_LIBRES.match(nombre)) and not _LICENCIAS_NO_LIBRES.search(nombre)


def image_is_safe(scores: dict[str, float]) -> bool:
    """Lo que dejó pasar la moderación de imagen."""
    return all(float(scores.get(k, 0.0) or 0.0) < tope for k, tope in _UMBRALES_IMAGEN.items())


def _texto_seguro(texto: str) -> str:
    """Sin HTML ni lo que cambia el sentido del markdown (enlaces, énfasis, código)."""
    sin_html = re.sub(r"<[^>]*>", "", texto or "")
    return re.sub(r"[\[\]()*_`<>|\\]", "", sin_html).strip()[:_MAX_TEXTO_ATRIBUCION]


def _markdown(img: LicensedImage) -> str:
    titulo = _texto_seguro(img.title) or "Imagen"
    autor = _texto_seguro(img.author) or "autor desconocido"
    licencia = _texto_seguro(img.license)
    licencia_md = f"[{licencia}]({img.license_url})" if img.license_url.startswith("https://") else licencia
    pagina = f"[Wikimedia Commons]({img.page_url})" if img.page_url.startswith("https://commons.wikimedia.org/") else "Wikimedia Commons"
    return f"![{titulo}]({img.url})\n*Foto: {autor} · {licencia_md} · {pagina}*"


def place_images(content: str, found: dict[str, "LicensedImage | None"]) -> tuple[str, list[dict[str, str]]]:
    """Cambia cada marca por su foto con la atribución, o la quita. Pura.

    Solo se entrega una imagen de Wikimedia (`upload.` o `thumb.wikimedia.org`): aunque el
    buscador devolviera otra cosa, al navegador del estudiante no llega.
    """
    if not content or "[[" not in content:
        return content, []
    visuales: list[dict[str, str]] = []

    def _decide(m: re.Match) -> str:
        img = found.get(m.group(1).strip())
        if img is None or not img.url.startswith(_ORIGENES_IMAGENES) or visuales:
            return ""
        visuales.append(img.to_dict())
        return _markdown(img)

    limpio = _MARCA_IMAGEN.sub(_decide, content)
    limpio = re.sub(r"\n{3,}", "\n\n", limpio).strip()
    return limpio, visuales
