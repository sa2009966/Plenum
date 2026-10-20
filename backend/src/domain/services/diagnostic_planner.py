"""Nivelación por rondas: qué preguntar, y qué veredicto sale (ADR-016, ADR-017).

Responde a "quiero aprender X" cuando no hay evidencia sobre el estudiante. No
genera texto ni habla con el modelo: eso es del prompt y del adaptador. Aquí solo
está la pedagogía.

Tres ideas sostienen el diseño:

1. **Rondas, no una tanda mezclada.** Una ronda que se aprueba y da paso a otra
   más dura es una experiencia que el estudiante entiende sin explicársela, y
   —sobre todo— produce un **veredicto de nivel**, que es lo que decide por dónde
   empieza la ruta de aprendizaje.
2. **Se prueba la base, no solo el tema.** Los ítems fáciles van a los
   prerrequisitos del grafo. Sin evidencia sobre la base, `PrerequisiteGate` no
   puede escalar a `OFFER` ni a `SEQUENCE`, y medio motor queda invisible.
3. **Aprobar es exigente.** En una nivelación, un falso "avanzado" hace más daño
   que un falso "intermedio": deja al estudiante con material por encima de su
   nivel y al sistema sin saber por qué se atasca.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.domain.aggregates.concept_graph import ConceptGraph
from src.domain.concept_identity import canonicalize_concept
from src.domain.value_objects.question import Difficulty

#: Cuántos prerrequisitos directos entran. Más de dos y la nivelación deja de ser
#: sobre el tema que el estudiante pidió.
MAX_PREREQUISITES = 2

#: Proporción de aciertos para superar una ronda. Hipótesis nombrada, como los
#: cutoffs del ADR-004: no es una constante física (ADR-017, decisión 2).
PASSING_RATIO = 0.75


class PlacementLevel(str, Enum):
    """Veredicto de nivel sobre un tema."""

    BASICO = "basico"
    INTERMEDIO = "intermedio"
    AVANZADO = "avanzado"


class PlacementRound(str, Enum):
    """Qué ronda se está administrando."""

    #: Lo básico del tema y su base. La que recibe quien llega sin historial.
    BASE = "base"
    #: El dominio real del tema. Solo la ve quien superó la anterior.
    AVANZADA = "avanzada"


@dataclass(frozen=True)
class DiagnosticRung:
    """Un peldaño: cuántos ítems, de qué dificultad y sobre qué conceptos."""

    difficulty: Difficulty
    items: int
    concepts: tuple[str, ...]
    #: Cuántos de `items` son preguntas abiertas (ADR-053). 0 = todas de opción múltiple.
    open_items: int = 0


@dataclass(frozen=True)
class DiagnosticPlan:
    """Qué medir y cómo, antes de generar una sola pregunta."""

    topic: str
    #: Ronda de nivelación, o None si es un cuestionario de PRÁCTICA: mismo plan
    #: de ítems, pero no escribe nivel (practicar no es nivelarse).
    round: PlacementRound | None
    concepts: tuple[str, ...]
    rungs: tuple[DiagnosticRung, ...]
    #: Cómo mostrárselo al estudiante. `topic` es la clave —sin tildes, para que
    #: "Electrónica" y "electronica" sean el mismo tema— y no sirve para pintar.
    label: str = ""
    #: Prueba de paso (ADR-042): lo que estudió en el tramo de su ruta (títulos e
    #: ideas clave). Con esto las preguntas salen de SU clase, no del tema en general.
    studied: tuple[str, ...] = ()

    @property
    def total_items(self) -> int:
        return sum(r.items for r in self.rungs)

    @property
    def open_items(self) -> int:
        return sum(r.open_items for r in self.rungs)

    @property
    def prerequisites(self) -> tuple[str, ...]:
        """Los conceptos del plan que no son el tema pedido."""
        return tuple(c for c in self.concepts if c != self.topic)


def display_label(typed: str) -> str:
    """El tema como lo escribió el estudiante, listo para mostrar.

    Se conservan tildes y mayúsculas ("historia de México"); solo se ordenan los
    espacios y se pone mayúscula inicial para que se lea como un título.
    """
    limpio = " ".join((typed or "").split()).strip(" .,;:!?¡¿")
    return limpio[:1].upper() + limpio[1:] if limpio else ""


def round_for(level: PlacementLevel | None) -> PlacementRound:
    """Qué ronda le toca a quien ya tiene este nivel en el tema.

    Quien no tiene nivel empieza por la base. Quien ya la superó —intermedio o
    avanzado— va a la avanzada: revalidar es legítimo y el mastery se actualiza
    con la evidencia nueva (ADR-017, decisión 4).
    """
    if level in (PlacementLevel.INTERMEDIO, PlacementLevel.AVANZADO):
        return PlacementRound.AVANZADA
    return PlacementRound.BASE


def resolve_placement(
    round_: PlacementRound, score_ratio: float, previous: PlacementLevel | None = None
) -> PlacementLevel:
    """Veredicto tras una ronda. Función pura.

    Suspender la ronda avanzada no degrada a quien ya era avanzado: el nivel
    guardado es el mejor alcanzado, y un mal día no borra lo demostrado. Lo que sí
    se mueve siempre es el mastery, que es la medida continua (ADR-017, decisión 5).
    """
    aprobo = score_ratio >= PASSING_RATIO
    if round_ == PlacementRound.BASE:
        alcanzado = PlacementLevel.INTERMEDIO if aprobo else PlacementLevel.BASICO
    else:
        alcanzado = PlacementLevel.AVANZADO if aprobo else PlacementLevel.INTERMEDIO
    if previous is None:
        return alcanzado
    orden = list(PlacementLevel)
    return max(alcanzado, previous, key=orden.index)


def has_next_round(round_: PlacementRound, level: PlacementLevel) -> bool:
    """Si tras esta ronda queda otra por administrar.

    Depende de la ronda que se acaba de hacer, no solo del nivel: quien suspende
    la avanzada también queda en `intermedio`, y mirando solo el nivel se le
    ofrecería repetirla en bucle. Se avanza por aprobar, no por quedarse.
    """
    return round_ == PlacementRound.BASE and level != PlacementLevel.BASICO


#: Reparto de cada ronda: (dificultad, ítems). El total sale de sumarlos.
_REPARTO: dict[PlacementRound, tuple[tuple[Difficulty, int], ...]] = {
    PlacementRound.BASE: ((Difficulty.EASY, 4), (Difficulty.MEDIUM, 2)),
    PlacementRound.AVANZADA: ((Difficulty.MEDIUM, 3), (Difficulty.HARD, 5)),
}


#: Reparto de un cuestionario de práctica según el nivel que ya tenga el
#: estudiante en el tema. Sin nivel se practica como un básico: ante la duda, la
#: práctica debe poder hacerse, no frustrar.
_PRACTICA: dict[PlacementLevel | None, tuple[tuple[Difficulty, float], ...]] = {
    None: ((Difficulty.EASY, 0.6), (Difficulty.MEDIUM, 0.4)),
    PlacementLevel.BASICO: ((Difficulty.EASY, 0.6), (Difficulty.MEDIUM, 0.4)),
    PlacementLevel.INTERMEDIO: (
        (Difficulty.EASY, 0.2), (Difficulty.MEDIUM, 0.6), (Difficulty.HARD, 0.2),
    ),
    PlacementLevel.AVANZADO: ((Difficulty.MEDIUM, 0.4), (Difficulty.HARD, 0.6)),
}
MAX_PRACTICE_ITEMS = 20


def _repartir(total: int, pesos: tuple[tuple[Difficulty, float], ...]) -> list[tuple[Difficulty, int]]:
    """Reparte `total` ítems según los pesos (mayor resto), sin peldaños vacíos."""
    brutos = [(d, total * p) for d, p in pesos]
    enteros = [[d, int(x)] for d, x in brutos]
    sobran = total - sum(n for _, n in enteros)
    for i in sorted(range(len(brutos)), key=lambda i: brutos[i][1] - int(brutos[i][1]), reverse=True)[:sobran]:
        enteros[i][1] += 1
    return [(d, n) for d, n in enteros if n > 0]


def plan_practice(
    topic: str,
    graph: ConceptGraph | None = None,
    level: PlacementLevel | None = None,
    items: int = 5,
) -> DiagnosticPlan:
    """Plan de un cuestionario de práctica sobre un tema, sin material.

    Como la nivelación, lo fácil prueba la base y lo demás el tema. A diferencia
    de ella, la dificultad sale del nivel que ya tenga el estudiante, y no deja
    veredicto: practicar no cambia el nivel guardado.
    """
    items = max(1, min(MAX_PRACTICE_ITEMS, int(items)))
    base_plan = plan_diagnostic(topic, graph, PlacementRound.BASE)
    base = base_plan.prerequisites or (base_plan.topic,)
    rungs = tuple(
        DiagnosticRung(
            difficulty=dificultad,
            items=n,
            concepts=base if dificultad == Difficulty.EASY else (base_plan.topic,),
        )
        for dificultad, n in _repartir(items, _PRACTICA[level])
    )
    return DiagnosticPlan(
        topic=base_plan.topic,
        round=None,
        concepts=base_plan.concepts,
        rungs=rungs,
        label=base_plan.label,
    )


def plan_diagnostic(
    topic: str,
    graph: ConceptGraph | None = None,
    round_: PlacementRound = PlacementRound.BASE,
) -> DiagnosticPlan:
    """Plan de una ronda de nivelación. Pura: mismo tema y ronda, mismo plan.

    Si el tema no está en el grafo —uno que el currículum no cubre— el plan sigue
    siendo válido y se mide solo el tema. Un tema desconocido no es un error: es un
    tema sin base declarada.
    """
    tema = canonicalize_concept(topic)
    if not tema:
        raise ValueError("El tema del diagnóstico no puede estar vacío.")

    prereqs: tuple[str, ...] = ()
    if graph is not None:
        tema = graph.canonicalize(tema)
        prereqs = graph.prerequisites_of(tema)[:MAX_PREREQUISITES]

    base = prereqs or (tema,)
    rungs = tuple(
        DiagnosticRung(
            difficulty=dificultad,
            items=items,
            # Lo fácil prueba la base; todo lo demás, el tema. Es lo que hace que
            # fallar la ronda base señale un hueco de prerrequisito y no del tema.
            concepts=base if dificultad == Difficulty.EASY else (tema,),
        )
        for dificultad, items in _REPARTO[round_]
    )
    return DiagnosticPlan(
        topic=tema,
        round=round_,
        concepts=(tema,) + prereqs,
        rungs=rungs,
        label=display_label(topic),
    )


#: Módulos del tramo que entran en una prueba de paso: más no caben en 6-8 preguntas.
MAX_PASSAGE_CONCEPTS = 8


def plan_passage_test(
    topic: str,
    label: str,
    round_: PlacementRound,
    concepts: tuple[str, ...],
    studied: tuple[str, ...] = (),
) -> DiagnosticPlan:
    """Prueba de paso de una ruta (ADR-042). Pura.

    Es una ronda de nivelación del MISMO tema (así el veredicto sube el nivel y abre
    el tramo siguiente por el camino de siempre), pero sus preguntas miden los
    módulos que estudió en el tramo, no el tema en general. Los ítems se etiquetan
    con esos conceptos: la evidencia llega a los módulos de la ruta.
    """
    tema = canonicalize_concept(topic)
    conceptos = tuple(dict.fromkeys(c for c in (canonicalize_concept(x) for x in concepts) if c))
    conceptos = conceptos[:MAX_PASSAGE_CONCEPTS]
    if not tema or not conceptos:
        raise ValueError("La prueba de paso necesita el tema y lo estudiado en la ruta.")
    rungs = tuple(
        DiagnosticRung(difficulty=dificultad, items=items, concepts=conceptos)
        for dificultad, items in _REPARTO[round_]
    )
    return DiagnosticPlan(
        topic=tema,
        round=round_,
        concepts=conceptos,
        rungs=rungs,
        label=label or display_label(topic),
        studied=tuple(studied),
    )


def resized(plan: DiagnosticPlan, total: int) -> DiagnosticPlan:
    """El mismo plan con `total` ítems, en la proporción de sus peldaños. Pura.

    La nivelación con abiertas tiene menos preguntas (ADR-053): escribir lleva más
    que marcar. Los peldaños que se quedan sin ítems desaparecen.
    """
    from dataclasses import replace

    from src.domain.assessment import split_by_weight

    nuevos = split_by_weight(max(1, total), [r.items for r in plan.rungs])
    rungs = tuple(
        replace(r, items=n, open_items=min(r.open_items, n)) for r, n in zip(plan.rungs, nuevos) if n > 0
    )
    return replace(plan, rungs=rungs)


def with_open_items(plan: DiagnosticPlan, n_open: int) -> DiagnosticPlan:
    """Reparte `n_open` abiertas entre los peldaños, en proporción a sus ítems. Pura."""
    from dataclasses import replace

    from src.domain.assessment import split_by_weight

    n_open = max(0, min(int(n_open), plan.total_items))
    abiertas = split_by_weight(n_open, [r.items for r in plan.rungs])
    rungs = tuple(replace(r, open_items=min(a, r.items)) for r, a in zip(plan.rungs, abiertas))
    return replace(plan, rungs=rungs)


def fit_to_plan(questions: list, plan: DiagnosticPlan) -> tuple[list, bool]:
    """Ajusta lo generado al reparto del plan. Devuelve (preguntas, cumple). Pura.

    El modelo no siempre respeta el reparto: en una ronda avanzada (3 medias y 5
    difíciles) llegó a devolver 10 ítems con 3 fáciles, que inflaban el aprobado.
    Aquí se toma, por peldaño y en orden, como mucho los ítems que pide; lo que no
    corresponde a ningún peldaño se descarta. `cumple` es False si algún peldaño
    quedó corto: quien llama decide si regenerar (ADR-045).
    """
    def _valor(d) -> str:
        # El adaptador da `Difficulty`; un doble o un JSON crudo, el texto ("hard").
        return getattr(d, "value", d)

    # Por dificultad Y por tipo (ADR-053): una abierta no ocupa el hueco de una de
    # opción múltiple, o la mezcla que eligió el estudiante no se cumpliría.
    quedan: dict[tuple[str, str], int] = {}
    for r in plan.rungs:
        d = _valor(r.difficulty)
        quedan[(d, "open")] = quedan.get((d, "open"), 0) + r.open_items
        quedan[(d, "choice")] = quedan.get((d, "choice"), 0) + r.items - r.open_items
    elegidas = []
    for q in questions:
        clave = (_valor(q.difficulty), getattr(q, "kind", "choice"))
        if quedan.get(clave, 0) > 0:
            elegidas.append(q)
            quedan[clave] -= 1
    return elegidas, all(v == 0 for v in quedan.values())
