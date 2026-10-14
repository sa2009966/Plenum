"""De la respuesta escrita del tutor a lo que se puede decir en voz alta (ADR-026).

Las respuestas traen markdown, fórmulas LaTeX, bloques de código y esquemas
dibujados con caracteres. Leídos tal cual, la voz diría "asterisco asterisco" o
"barra paréntesis a equis". Lo visual se sustituye por un aviso breve: está en
pantalla, y la voz no lo puede describir bien.
"""
from __future__ import annotations

import re

AVISO_CODIGO = "Te dejo el código en pantalla."
AVISO_FORMULA = "la fórmula que ves en pantalla"
AVISO_ESQUEMA = "Te dejo un esquema en pantalla."

_BLOQUE_CODIGO = re.compile(r"```.*?(?:```|$)", re.S)
#: Un esquema Mermaid (ADR-048) es un dibujo, no código: la voz avisa de eso.
_BLOQUE_ESQUEMA = re.compile(r"```[ \t]*mermaid\b.*?(?:```|$)", re.S | re.I)
_FORMULA_BLOQUE = re.compile(r"\$\$.*?\$\$|\\\[.*?\\\]", re.S)
_FORMULA_LINEA = re.compile(r"\\\((.*?)\\\)|\$(?!\s)([^$\n]{1,200}?)\$")
_ENLACE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_CODIGO_LINEA = re.compile(r"`([^`]*)`")
_ENFASIS = re.compile(r"(\*\*|__|\*|_|~~)(?=\S)(.+?)(?<=\S)\1")
_ENCABEZADO = re.compile(r"^\s{0,3}#{1,6}\s*", re.M)
_CITA = re.compile(r"^\s*>\s?", re.M)
_VINETA = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+", re.M)
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿️]")

#: Una fórmula "simple" se lee; una con comandos LaTeX (\frac, \sum…) no.
_LATEX_COMANDO = re.compile(r"\\[a-zA-Z]+|[_^{}]")


def _es_esquema(linea: str) -> bool:
    """Línea de dibujo o tabla: muchos |, +, -, =, cajas o flechas."""
    s = linea.strip()
    if not s:
        return False
    if len(s) >= 2 and s[0] in "|│+┌└├" and s[-1] in "|│+┐┘┤":
        return True  # fila de una caja o tabla: "|  Base  |"
    dibujo = sum(s.count(c) for c in "|+-=_/\\┌┐└┘│─├┤┬┴┼→←↑↓")
    return dibujo / len(s) > 0.3


_SIMPLE = r"[A-Za-z0-9.]+"
#: LaTeX que sí se puede decir. Lo que quede con comandos o llaves tras esto se
#: avisa: una integral leída a medias confunde más que "la fórmula en pantalla".
_A_VOZ: list[tuple[re.Pattern[str], str]] = [
    (re.compile(rf"\\[dt]?frac\{{({_SIMPLE})\}}\{{({_SIMPLE})\}}"), r"\1 sobre \2"),
    (re.compile(rf"\\sqrt\{{({_SIMPLE})\}}"), r"raíz de \1"),
    (re.compile(rf"({_SIMPLE})\^\{{?2\}}?"), r"\1 al cuadrado"),
    (re.compile(rf"({_SIMPLE})\^\{{?3\}}?"), r"\1 al cubo"),
    (re.compile(rf"({_SIMPLE})\^\{{?({_SIMPLE})\}}?"), r"\1 elevado a \2"),
    (re.compile(r"\\(?:cdot|times)"), " por "),
    (re.compile(r"\\div"), " entre "),
    (re.compile(r"\\pi\b"), "pi"),
    (re.compile(r"\\(?:leq|le)\b"), " menor o igual que "),
    (re.compile(r"\\(?:geq|ge)\b"), " mayor o igual que "),
    (re.compile(r"\\neq\b"), " distinto de "),
    (re.compile(r"\\[,;! ]"), " "),
]


def _formula_a_voz(cuerpo: str) -> str | None:
    for patron, voz in _A_VOZ:
        cuerpo = patron.sub(voz, cuerpo)
    return None if _LATEX_COMANDO.search(cuerpo) else re.sub(r"\s+", " ", cuerpo).strip()


def _formula_en_linea(m: re.Match) -> str:
    cuerpo = (m.group(1) or m.group(2) or "").strip()
    return (_formula_a_voz(cuerpo) if cuerpo else None) or AVISO_FORMULA


def speakable_text(texto: str) -> str:
    if not texto:
        return ""
    t = _BLOQUE_ESQUEMA.sub(f"\n{AVISO_ESQUEMA}\n", texto)
    t = _BLOQUE_CODIGO.sub(f"\n{AVISO_CODIGO}\n", t)
    t = _FORMULA_BLOQUE.sub(f" {AVISO_FORMULA} ", t)
    t = _FORMULA_LINEA.sub(_formula_en_linea, t)

    lineas, en_esquema = [], False
    for linea in t.splitlines():
        if _es_esquema(linea):
            if not en_esquema:
                lineas.append(AVISO_ESQUEMA)
            en_esquema = True
            continue
        en_esquema = False
        lineas.append(linea)
    t = "\n".join(lineas)

    t = _ENLACE.sub(r"\1", t)
    t = _CODIGO_LINEA.sub(r"\1", t)
    for _ in range(2):  # énfasis anidado: **_así_**
        t = _ENFASIS.sub(r"\2", t)
    t = _ENCABEZADO.sub("", t)
    t = _CITA.sub("", t)
    t = _VINETA.sub("", t)
    t = _EMOJI.sub("", t)
    t = re.sub(r"[*#`|]", " ", t)
    # Cada línea es una pausa: sin punto final, la voz las encadena sin respirar.
    frases = [ln.strip() for ln in t.splitlines() if ln.strip()]
    frases = [f if f[-1] in ".!?:;…," else f + "." for f in frases]
    return re.sub(r"\s+", " ", " ".join(frases)).strip()
