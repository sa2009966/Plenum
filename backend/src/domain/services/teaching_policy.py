"""Decisiones de la clase: qué concepto, qué explicación, cuándo avanzar o remediar (ADR-028).

Pura y determinista. El modelo NO decide nada de esto: solo redacta la
explicación, el ejemplo y las preguntas que esta política pide.

Reutiliza las piezas que ya deciden en el resto del sistema:
- el mastery efectivo y `has_decision_evidence` del perfil (invariante 3);
- `PrerequisiteGate` sobre el grafo de la propia ruta (invariante 5): solo se
  desvía a un prerrequisito con evidencia, o cuando el concepto falla de forma
  repetida.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.domain.aggregates.concept_graph import ConceptGraph
from src.domain.aggregates.learning_path import (
    MASTERY_COMPLETED,
    tier_index,
    CheckOutcome,
    LearningModule,
    LearningPathAggregate,
    LessonVariant,
    ModuleKind,
    TeachingPhase,
)
from src.domain.aggregates.student_profile import StudentProfile
from src.domain.services.prerequisite_graph import GateAction, PrerequisiteGate
from src.domain.value_objects.question import Difficulty


@dataclass(frozen=True)
class NextStep:
    phase: TeachingPhase
    concept: str | None
    variant: LessonVariant | None
    return_to: str | None = None
    #: Por qué, en una frase para el estudiante (decir por qué, ADR-013).
    reason: str = ""


class TeachingPolicy:
    def __init__(
        self,
        mastery_completed: float = MASTERY_COMPLETED,
        understood_to_advance: int = 2,
        failures_to_remediate: int = 2,
        gate_min_mastery: float = 0.45,
        review_below: float = 0.5,
    ) -> None:
        self._completed = mastery_completed
        # Dos comprobaciones seguidas superadas bastan aunque el EMA del mastery
        # aún no llegue al umbral: si no, un estudiante que acierta todo se
        # quedaría comprobando el mismo concepto hasta que el promedio suba.
        self._understood_to_advance = understood_to_advance
        self._failures_to_remediate = failures_to_remediate
        self._gate_min_mastery = gate_min_mastery
        self._review_below = review_below

    # --- Lectura del perfil -------------------------------------------------------

    @staticmethod
    def _mastery(profile: StudentProfile | None, concept: str) -> float:
        return profile.effective_concept_mastery(concept) if profile else 0.0

    @staticmethod
    def _measured(profile: StudentProfile | None, concept: str) -> bool:
        return bool(profile and profile.has_decision_evidence(concept))

    def _graph(self, path: LearningPathAggregate) -> ConceptGraph:
        g = ConceptGraph(graph_id=f"path:{path.id}")
        for concept, pre in path.prerequisite_edges():
            g.curate(concept, pre)
        return g

    def _gate(self, path: LearningPathAggregate) -> PrerequisiteGate:
        return PrerequisiteGate(graph=self._graph(path), min_mastery=self._gate_min_mastery)

    def due_review(self, path: LearningPathAggregate, profile: StudentProfile | None) -> str | None:
        """Un concepto superado en clase cuyo dominio efectivo cayó por el olvido.

        El mastery efectivo ya decae con el tiempo (Ebbinghaus); hasta ahora
        nadie actuaba sobre eso. Si un concepto superado baja de
        `review_below`, toca repasarlo antes de seguir: es el que más se aleja
        de lo que el estudiante sabía (ADR-032).
        """
        if profile is None:
            return None
        candidatos = [
            (self._mastery(profile, c), c)
            for c in path.teaching.passed_concepts
            if self._measured(profile, c) and self._mastery(profile, c) < self._review_below
        ]
        return min(candidatos)[1] if candidatos else None

    def tier_to_open(self, path: LearningPathAggregate, profile: StudentProfile | None) -> str | None:
        """El tramo que toca abrir porque el nivel del tema superó al tramo actual (ADR-037).

        El nivel sale de la nivelación, que es evidencia calificada: el tramo no se
        abre porque el cliente lo pida, sino porque el estudiante lo demostró. Si
        saltó directamente a avanzado, se abre avanzado: no se le hace repetir lo
        que ya probó.
        """
        if not (path.topic and path.tiers and profile):
            return None
        nivel = profile.level_for_topic(path.topic)
        return nivel if tier_index(nivel) > tier_index(path.current_tier) else None

    @staticmethod
    def _fin_de_tramo(path: LearningPathAggregate) -> str:
        siguiente = path.next_tier
        if siguiente is None:
            return "Completaste la ruta."
        return (
            f"Completaste el tramo {_NOMBRE_TRAMO[path.current_tier]}. Haz la prueba de paso "
            f"(la nivelación de «{path.title}») para abrir el tramo {_NOMBRE_TRAMO[siguiente]}."
        )

    def needs_teaching(self, path: LearningPathAggregate, profile: StudentProfile | None, m: LearningModule) -> bool:
        """Si un módulo todavía hay que enseñarlo."""
        if m.concept in path.teaching.passed_concepts:
            return False
        dominado = self._mastery(profile, m.concept) >= self._completed
        if m.kind == ModuleKind.CONTENT:
            # Lo que vino a aprender no se da por visto con dos preguntas medias de
            # la nivelación: hace falta superarlo en clase, o el veredicto
            # "avanzado" (que sí probó lo difícil). Sin esto, quien sale
            # "intermedio" veía su ruta completada antes de la primera clase.
            nivel = profile.level_for_topic(path.topic) if (profile and path.topic) else None
            return not (dominado and nivel == "avanzado")
        if dominado:
            return False
        # Un prerrequisito sin medir se da por sabido: no medido ≠ medido en
        # cero. Se enseña solo si hay evidencia de que flojea (o si el gate lo
        # pide al fallar el tema, ver `after_check`).
        if m.kind == ModuleKind.PREREQUISITE and not self._measured(profile, m.concept):
            return False
        return True

    # --- Decisiones ---------------------------------------------------------------

    def next_concept(
        self,
        path: LearningPathAggregate,
        profile: StudentProfile | None,
        *,
        exclude: str | None = None,
    ) -> NextStep:
        """El siguiente concepto de la ruta: repaso si algo se olvidó; si no, el siguiente pendiente."""
        repaso = self.due_review(path, profile)
        if repaso and repaso != exclude:
            return NextStep(
                TeachingPhase.TEACHING,
                repaso,
                LessonVariant.REVIEW,
                reason=f"Hace un tiempo que no practicas «{self._titulo(path, repaso)}»: lo repasamos un momento.",
            )
        pendientes = [
            m for m in sorted(path.modules, key=lambda x: x.position)
            if m.concept != exclude and self.needs_teaching(path, profile, m)
        ]
        if not pendientes:
            return NextStep(TeachingPhase.COMPLETED, None, None, reason=self._fin_de_tramo(path))
        objetivo = pendientes[0]
        gate = self._gate(path).evaluate(objetivo.concept, profile)
        # Solo SEQUENCE lidera con la base (invariante 5): exige evidencia medida
        # y repetida. Con menos, se enseña el concepto y el gate no desvía.
        if gate.action == GateAction.SEQUENCE and gate.remediation_focus:
            base = gate.remediation_focus[0]
            return NextStep(
                TeachingPhase.REMEDIATION,
                base,
                LessonVariant.REMEDIATE,
                return_to=objetivo.concept,
                reason=f"Antes de «{self._titulo(path, objetivo.concept)}» repasamos "
                f"«{self._titulo(path, base)}», que te está costando. Luego volvemos.",
            )
        fase = TeachingPhase.ADVANCE if path.teaching.passed_concepts else TeachingPhase.TEACHING
        return NextStep(fase, objetivo.concept, LessonVariant.INTRODUCE)

    def after_check(
        self,
        path: LearningPathAggregate,
        outcome: CheckOutcome,
        profile: StudentProfile | None,
    ) -> NextStep:
        """Qué toca después de una comprobación. `path.teaching` ya registró el resultado."""
        t = path.teaching
        concepto = t.concept
        if concepto is None:
            raise ValueError("No hay concepto en curso.")

        if outcome == CheckOutcome.UNDERSTOOD:
            dominado = (
                self._mastery(profile, concepto) >= self._completed
                or t.understood_streak >= self._understood_to_advance
            )
            if not dominado:
                return NextStep(
                    TeachingPhase.TEACHING,
                    concepto,
                    LessonVariant.CONSOLIDATE,
                    return_to=t.return_to,
                    reason="¡Bien! Una comprobación más para afianzarlo.",
                )
            path.mark_passed(concepto)
            if t.return_to:
                return NextStep(
                    TeachingPhase.TEACHING,
                    t.return_to,
                    LessonVariant.RESUME,
                    reason=f"Ya tienes la base. Volvemos a «{self._titulo(path, t.return_to)}».",
                )
            siguiente = self.next_concept(path, profile, exclude=concepto)
            if siguiente.phase == TeachingPhase.TEACHING:
                siguiente = NextStep(TeachingPhase.ADVANCE, siguiente.concept, siguiente.variant)
            return siguiente

        if outcome == CheckOutcome.PARTIAL:
            return NextStep(
                TeachingPhase.TEACHING,
                concepto,
                LessonVariant.NEW_EXAMPLE,
                return_to=t.return_to,
                reason="Vas bien, pero no del todo. Lo vemos con otro ejemplo.",
            )

        # NO ENTENDIÓ: ¿falta una base? El gate decide con la evidencia, incluida
        # la de esta comprobación (ya está en el perfil).
        gate = self._gate(path).evaluate(concepto, profile)
        base = next(
            (
                r for r in gate.remediation_focus
                if r != concepto and r not in t.passed_concepts and self._mastery(profile, r) < self._completed
            ),
            None,
        )
        con_evidencia = gate.action in (GateAction.SEQUENCE, GateAction.OFFER)
        insiste = t.failures_on_concept >= self._failures_to_remediate
        if base and (con_evidencia or insiste):
            return NextStep(
                TeachingPhase.REMEDIATION,
                base,
                LessonVariant.REMEDIATE,
                return_to=t.return_to or concepto,
                reason=f"Parece que falta una base: repasamos «{self._titulo(path, base)}» "
                f"y luego volvemos a «{self._titulo(path, t.return_to or concepto)}».",
            )
        return NextStep(
            TeachingPhase.TEACHING,
            concepto,
            LessonVariant.REFORMULATE,
            return_to=t.return_to,
            reason="Lo explico de otra manera, más paso a paso.",
        )

    @staticmethod
    def _titulo(path: LearningPathAggregate, concept: str) -> str:
        m = path.module(concept)
        return m.title if m else concept


_NOMBRE_TRAMO = {"basico": "básico", "intermedio": "intermedio", "avanzado": "avanzado"}


def outcome_from(correct: int, total: int) -> CheckOutcome:
    """Todas bien = entendió; ninguna = no entendió; en medio = parcialmente."""
    if total <= 0 or correct <= 0:
        return CheckOutcome.NOT_UNDERSTOOD
    if correct >= total:
        return CheckOutcome.UNDERSTOOD
    return CheckOutcome.PARTIAL


#: Dificultad de las 2 preguntas de la comprobación según el tipo de explicación.
#: Tras no entender, preguntas accesibles; para afianzar, más exigentes.
_DIFICULTADES = {
    LessonVariant.INTRODUCE: ("easy", "medium"),
    LessonVariant.NEW_EXAMPLE: ("easy", "medium"),
    LessonVariant.REFORMULATE: ("easy", "easy"),
    LessonVariant.REMEDIATE: ("easy", "easy"),
    LessonVariant.CONSOLIDATE: ("medium", "hard"),
    LessonVariant.RESUME: ("easy", "medium"),
    LessonVariant.REVIEW: ("medium", "medium"),
}


def check_difficulties(variant: LessonVariant) -> tuple[Difficulty, ...]:
    return tuple(Difficulty(d) for d in _DIFICULTADES[variant])
