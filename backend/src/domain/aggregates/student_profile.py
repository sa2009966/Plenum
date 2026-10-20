from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from math import exp, log
from uuid import UUID

from src.domain.concept_identity import canonicalize_concept
from src.domain.adaptive_signals import DEFAULT_CUTOFFS, Signal, SignalKind
from src.domain import memory_model
from src.domain.memory_model import ReviewEntry


DEFAULT_HALF_LIFE_DAYS = 14.0
HIGH_LATENCY_THRESHOLD_MS = 8000.0
_MAX_APPLIED_EVENT_IDS = 256
#: Cuánto pesa una evidencia débil (auto-reporte, comportamiento, chat) frente a
#: un ítem calificado. Hipótesis nombrada, como los cutoffs del ADR-004: decir
#: "no entiendo" es información, pero no es una medición (ADR-007).
WEAK_EVIDENCE_WEIGHT = 0.5
#: Evidencia —en unidades de ítem calificado— que un concepto necesita para
#: informar la decisión en caliente (modo, dificultad, foco). Un solo
#: auto-reporte queda por debajo: preguntar no es fallar.
MIN_EVIDENCE_FOR_DECISION = 1.0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _norm_concept(label: str) -> str:
    return canonicalize_concept(label)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class EvidenceKind(str, Enum):
    QUIZ_ITEM = "quiz_item"
    ASK_STRUGGLE = "ask_struggle"
    HELP_REQUEST = "help_request"
    HIGH_LATENCY = "high_latency"
    REPEATED_ERROR = "repeated_error"
    SUCCESS = "success"


#: Señales que el estudiante reporta o que se infieren de su comportamiento.
#: No son ítems calificados: describen cómo pide ayuda, no qué sabe (ADR-007).
_WEAK_EVIDENCE_KINDS = frozenset(
    {
        EvidenceKind.ASK_STRUGGLE,
        EvidenceKind.HELP_REQUEST,
        EvidenceKind.HIGH_LATENCY,
    }
)


@dataclass(frozen=True)
class EvidenceSample:
    """Señal de aprendizaje multi-fuente para actualizar mastery."""

    kind: EvidenceKind
    score_ratio: float
    weight: float = 1.0
    latency_ms: float | None = None
    help_level: float = 0.0  # 0..1
    document_id: UUID | None = None
    subject: str | None = None
    at: datetime | None = None
    # Evidencia débil (p. ej. autocorregirse en el chat): nunca fija el mastery
    # por sí sola ni borra una racha de error de golpe. Sin esto, un solo
    # mensaje llevaba un concepto de 0.00 a 0.76 y desarmaba `SEQUENCE`.
    is_weak: bool = False

    @property
    def is_weak_evidence(self) -> bool:
        """Débil = no calificada: auto-reporte, comportamiento o conversación.

        La clase de la señal manda sobre el flag: un `ASK_STRUGGLE` es débil
        aunque quien construya la muestra olvide marcarlo.
        """
        return self.is_weak or self.kind in _WEAK_EVIDENCE_KINDS


@dataclass
class PedagogicalMemory:
    """Memoria educativa compacta (no historial conversacional)."""

    frequent_misconceptions: list[str] = field(default_factory=list)
    successful_examples: list[str] = field(default_factory=list)
    successful_analogies: list[str] = field(default_factory=list)
    # Vacío = sin preferencia observada. Un default "simple" cortocircuitaba
    # las heurísticas de CognitiveStyleSelector y congelaba el estilo de todo
    # estudiante en SIMPLE de por vida (ADR-006, fase 2).
    preferred_explanation_style: str = ""
    last_effective_strategies: list[str] = field(default_factory=list)

    def remember_misconception(self, label: str) -> None:
        key = _norm_concept(label)
        if not key:
            return
        if key in self.frequent_misconceptions:
            self.frequent_misconceptions.remove(key)
        self.frequent_misconceptions.insert(0, key)
        self.frequent_misconceptions = self.frequent_misconceptions[:15]

    def remember_example(self, example: str) -> None:
        text = (example or "").strip()
        if not text:
            return
        if text in self.successful_examples:
            self.successful_examples.remove(text)
        self.successful_examples.insert(0, text[:240])
        self.successful_examples = self.successful_examples[:10]

    def remember_analogy(self, analogy: str) -> None:
        text = (analogy or "").strip()
        if not text:
            return
        if text in self.successful_analogies:
            self.successful_analogies.remove(text)
        self.successful_analogies.insert(0, text[:240])
        self.successful_analogies = self.successful_analogies[:10]

    def set_preferred_style(self, style: str) -> None:
        """Solo se llama ante evidencia de que el estilo funcionó."""
        self.preferred_explanation_style = (style or "").strip().lower()

    def remember_strategy(self, strategy: str) -> None:
        key = (strategy or "").strip().lower()
        if not key:
            return
        if key in self.last_effective_strategies:
            self.last_effective_strategies.remove(key)
        self.last_effective_strategies.insert(0, key)
        self.last_effective_strategies = self.last_effective_strategies[:8]


@dataclass
class ConceptMastery:
    """Dominio estimado de un concepto a partir de evidencia multi-señal + olvido."""

    concept_key: str
    attempts: int = 0
    mastery: float = 0.0
    last_score_ratio: float = 0.0
    document_ids: list[UUID] = field(default_factory=list)
    confidence: float = 0.0
    last_practiced_at: datetime | None = None
    help_requests: int = 0
    latency_ms_ema: float = 0.0
    error_streak: int = 0
    subject: str | None = None
    evidence_count: int = 0
    # Subconjunto de `evidence_count` que no vino de un ítem calificado. Se
    # cuenta aparte para poder pesar la evidencia por su calidad sin perder el
    # total (ADR-007).
    weak_evidence_count: int = 0
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS
    #: Último repaso CALIFICADO (ADR-051). `last_practiced_at` también se mueve con
    #: el chat; la memoria solo se mide con ítems corregidos en servidor.
    last_reviewed_at: datetime | None = None
    #: Repasos calificados, el más antiguo primero; acotado a MAX_REVIEW_LOG.
    review_log: list[ReviewEntry] = field(default_factory=list)

    def record_review(self, score_ratio: float, at: datetime | None = None) -> None:
        """Un repaso calificado de este concepto: ajusta la vida media (ADR-051).

        Se llama una vez por concepto y por intento, no por ítem: ocho preguntas
        del mismo concepto en un quiz son un repaso, no ocho.
        """
        momento = _aware(at or _utc_now())
        if self.last_reviewed_at is None:
            self.half_life_days = memory_model.first_half_life(score_ratio)
        else:
            transcurrido = max(0.0, (momento - _aware(self.last_reviewed_at)).total_seconds() / 86400.0)
            self.half_life_days = memory_model.next_half_life(self.half_life_days, transcurrido, score_ratio)
        self.last_reviewed_at = momento
        self.review_log.append(
            ReviewEntry(at=momento, score_ratio=max(0.0, min(1.0, score_ratio)), half_life_days=self.half_life_days)
        )
        self.review_log = self.review_log[-memory_model.MAX_REVIEW_LOG:]

    @property
    def measured_evidence_count(self) -> int:
        """Evidencia calificada: quizzes e ítems corregidos en servidor."""
        return max(0, self.evidence_count - self.weak_evidence_count)

    @property
    def weighted_evidence(self) -> float:
        """Evidencia en unidades de ítem calificado.

        Un auto-reporte cuenta `WEAK_EVIDENCE_WEIGHT`: informa, pero hacen
        falta dos para pesar lo que pesa un ítem que se falló de verdad.
        """
        return self.measured_evidence_count + (
            WEAK_EVIDENCE_WEIGHT * self.weak_evidence_count
        )

    @property
    def informs_decision(self) -> bool:
        """Si este concepto puede mover modo/dificultad/foco en este turno."""
        return self.weighted_evidence >= MIN_EVIDENCE_FOR_DECISION

    def apply_result(
        self, score_ratio: float, document_id: UUID | None = None, alpha: float = 0.45
    ) -> None:
        """Compatibilidad: acierto/fallo de ítem como evidencia de quiz."""
        self.apply_evidence(
            EvidenceSample(
                kind=EvidenceKind.QUIZ_ITEM,
                score_ratio=score_ratio,
                weight=alpha / 0.45 if alpha else 1.0,
                document_id=document_id,
            )
        )

    def apply_evidence(self, sample: EvidenceSample, alpha: float = 0.45) -> None:
        ratio = max(0.0, min(1.0, float(sample.score_ratio)))
        w = max(0.05, min(2.0, float(sample.weight)))
        effective_alpha = max(0.05, min(0.9, alpha * w))

        # Ajustes por tipo de señal
        if sample.kind == EvidenceKind.HELP_REQUEST:
            self.help_requests += 1
            ratio = min(ratio, 0.45)
            effective_alpha = max(effective_alpha, 0.35)
            # La dificultad repetida en el chat también es dificultad repetida.
            # Sin esto, `error_streak` solo crecía con quizzes y `SEQUENCE` era
            # inalcanzable para quien aprende conversando (ADR-006).
            self.error_streak += 1
        elif sample.kind == EvidenceKind.ASK_STRUGGLE:
            ratio = min(ratio, 0.35)
            effective_alpha = max(effective_alpha, 0.4)
            self.error_streak += 1
        elif sample.kind == EvidenceKind.HIGH_LATENCY:
            # Latencia alta reduce confianza y tira ligeramente el mastery
            ratio = min(ratio, max(0.0, ratio - 0.15))
            effective_alpha = max(0.2, effective_alpha * 0.7)
        elif sample.kind == EvidenceKind.REPEATED_ERROR:
            ratio = min(ratio, 0.25)
            effective_alpha = max(effective_alpha, 0.5)
            self.error_streak += 1
        elif sample.kind in (EvidenceKind.QUIZ_ITEM, EvidenceKind.SUCCESS):
            if ratio < 0.5:
                self.error_streak += 1
            elif sample.is_weak:
                # Un acierto débil descuenta la racha, no la borra: si no,
                # una frase de cortesía anula varios fallos calificados.
                self.error_streak = max(0, self.error_streak - 1)
            else:
                self.error_streak = 0

        # Una observación por turno: la latencia alta penaliza la muestra que
        # ya describe ese turno. Antes se añadía una muestra HIGH_LATENCY
        # aparte sobre el mismo concepto, así que un turno lento contaba dos
        # veces en `attempts` y corría dos veces la EWMA.
        if (
            sample.kind != EvidenceKind.HIGH_LATENCY
            and sample.latency_ms is not None
            and sample.latency_ms >= HIGH_LATENCY_THRESHOLD_MS
        ):
            ratio = max(0.0, ratio - 0.15)

        if sample.help_level > 0:
            self.help_requests += 1 if sample.help_level >= 0.4 else 0
            # Más ayuda → menos crédito al acierto aparente
            ratio = ratio * (1.0 - 0.35 * max(0.0, min(1.0, sample.help_level)))

        self.attempts += 1
        self.evidence_count += 1
        if sample.is_weak_evidence:
            self.weak_evidence_count += 1
        self.last_score_ratio = ratio
        if self.attempts == 1 and not sample.is_weak_evidence:
            self.mastery = ratio
        else:
            # La evidencia débil siempre pasa por la EWMA, incluso siendo la
            # primera: certificar un concepto con un solo mensaje sería
            # corromper el mastery, no medirlo.
            self.mastery = (effective_alpha * ratio) + ((1.0 - effective_alpha) * self.mastery)

        # Confianza crece con evidencia consistente; baja con errores/ayuda
        conf_delta = 0.08 * w
        if ratio >= 0.7 and sample.kind != EvidenceKind.HELP_REQUEST:
            self.confidence = min(1.0, self.confidence + conf_delta)
        elif ratio < 0.5:
            self.confidence = max(0.0, self.confidence - conf_delta * 1.2)
        else:
            self.confidence = min(1.0, self.confidence + conf_delta * 0.4)
        if sample.kind == EvidenceKind.HELP_REQUEST:
            self.confidence = max(0.0, self.confidence - 0.05)

        if sample.latency_ms is not None and sample.latency_ms > 0:
            lat = float(sample.latency_ms)
            if self.latency_ms_ema <= 0:
                self.latency_ms_ema = lat
            else:
                self.latency_ms_ema = 0.3 * lat + 0.7 * self.latency_ms_ema

        if sample.document_id is not None and sample.document_id not in self.document_ids:
            self.document_ids.append(sample.document_id)
        if sample.subject:
            self.subject = _norm_concept(sample.subject)
        self.last_practiced_at = sample.at or _utc_now()

    def effective_mastery(self, now: datetime | None = None) -> float:
        """Mastery con decaimiento exponencial (Ebbinghaus). No castiga: recuerda repasar."""
        base = max(0.0, min(1.0, self.mastery))
        if self.last_practiced_at is None or self.attempts == 0:
            return base
        moment = now or _utc_now()
        practiced = self.last_practiced_at
        if practiced.tzinfo is None:
            practiced = practiced.replace(tzinfo=timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        days = max(0.0, (moment - practiced).total_seconds() / 86400.0)
        half = max(1.0, float(self.half_life_days or DEFAULT_HALF_LIFE_DAYS))
        # retention = 0.5 ** (days / half_life)
        retention = exp(-log(2.0) * days / half)
        # Confianza también decae (suave)
        conf_factor = 0.55 + 0.45 * max(0.0, min(1.0, self.confidence))
        return max(0.0, min(1.0, base * retention * (0.85 + 0.15 * conf_factor)))

    def forgetting_gap(self, now: datetime | None = None) -> float:
        """Cuánto cayó el mastery efectivo respecto al stored (0..1)."""
        stored = max(0.0, min(1.0, self.mastery))
        return max(0.0, stored - self.effective_mastery(now))


@dataclass
class DocumentMastery:
    """Dominio estimado de un documento a partir de intentos y señales ask."""

    document_id: UUID
    attempts: int = 0
    mastery: float = 0.0
    last_score_ratio: float = 0.0
    incorrect_streak: int = 0
    struggle_signals: int = 0

    def apply_result(self, score_ratio: float, alpha: float = 0.4) -> None:
        ratio = max(0.0, min(1.0, float(score_ratio)))
        self.attempts += 1
        self.last_score_ratio = ratio
        if self.attempts == 1:
            self.mastery = ratio
        else:
            self.mastery = (alpha * ratio) + ((1.0 - alpha) * self.mastery)
        if ratio < 0.5:
            self.incorrect_streak += 1
        else:
            self.incorrect_streak = 0

    def apply_soft_struggle(self, pull_toward: float = 0.2, weight: float = 0.5) -> None:
        target = max(0.0, min(1.0, pull_toward))
        w = max(0.0, min(1.0, weight))
        self.mastery = (w * target) + ((1.0 - w) * self.mastery)
        self.struggle_signals += 1
        self.last_score_ratio = min(self.last_score_ratio, target)


@dataclass
class StudentProfile:
    """Perfil cognitivo: mastery por documento/concepto + memoria pedagógica."""

    student_id: UUID
    mastery_by_document: dict[UUID, DocumentMastery] = field(default_factory=dict)
    mastery_by_concept: dict[str, ConceptMastery] = field(default_factory=dict)
    frequent_errors: list[str] = field(default_factory=list)
    pace: str = "steady"
    total_attempts: int = 0
    total_struggle_signals: int = 0
    pedagogical_memory: PedagogicalMemory = field(default_factory=PedagogicalMemory)
    learning_velocity: float = 0.0  # EMA de deltas de mastery
    applied_event_ids: list[str] = field(default_factory=list)
    # Conceptos cuyo dominio ya se le reconoció al estudiante. Celebrar de más
    # quema el canal, así que el hito es irrepetible por concepto (ADR-009).
    celebrated_concepts: list[str] = field(default_factory=list)
    # Estado de interacción: fuente de verdad única para interaction_gap_ms.
    # El gap se calcula en el borde (servicio que recibe la pregunta) con
    # wall-clock real, nunca en el projector. Ver ADR-004, Decisión 2.
    last_interaction_at: datetime | None = None
    last_answer_length: int = 0
    adaptive_signals: dict[str, Signal] = field(default_factory=dict)
    # Veredicto de nivelación por tema (ADR-017). Resume, no sustituye: si
    # alguna vez discrepa del mastery manda el mastery, que se mide de forma
    # continua. Este se recalcula en la siguiente nivelación.
    level_by_topic: dict[str, str] = field(default_factory=dict)
    #: Cómo mostrar cada tema de `level_by_topic` (mismas claves).
    topic_labels: dict[str, str] = field(default_factory=dict)
    #: Cómo eligió el estudiante que le expliquen (ADR-022). Vacío = que decida
    #: LARIA. No es lo mismo que `pedagogical_memory.preferred_explanation_style`,
    #: que es lo DEDUCIDO de lo que le funcionó.
    explanation_style_choice: str = ""
    #: Voz del tutor que eligió (ADR-030). Vacío = la de por defecto.
    voice_choice: str = ""
    #: Minutos por sesión de clase (10/20/30/45); 0 = sin límite (ADR-033).
    session_minutes: int = 0
    #: Objetivo diario en minutos (10/15/30/45/60); 0 = sin objetivo.
    daily_goal_minutes: int = 0
    updated_at: datetime = field(default_factory=_utc_now)
    version: int = 0

    def was_event_applied(self, event_id: UUID) -> bool:
        return str(event_id) in self.applied_event_ids

    def mark_event_applied(self, event_id: UUID) -> None:
        key = str(event_id)
        if key in self.applied_event_ids:
            return
        self.applied_event_ids.append(key)
        if len(self.applied_event_ids) > _MAX_APPLIED_EVENT_IDS:
            self.applied_event_ids = self.applied_event_ids[-_MAX_APPLIED_EVENT_IDS:]

    @staticmethod
    def create(student_id: UUID) -> "StudentProfile":
        return StudentProfile(student_id=student_id)

    def interaction_gap_ms(self, now: datetime | None = None) -> float | None:
        """Milisegundos desde la última interacción, o None si es la primera.

        Fuente de verdad única del gap. Los servicios lo piden aquí; no lo
        reconstruyen por su cuenta ni lo derivan del projector.
        """
        if self.last_interaction_at is None:
            return None
        moment = now or _utc_now()
        previous = self.last_interaction_at
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return max(0.0, (moment - previous).total_seconds() * 1000.0)

    def record_interaction(self, answer_length: int, at: datetime | None = None) -> None:
        """Cierra el turno: fija el reloj y el largo de la respuesta entregada."""
        self.last_interaction_at = at or _utc_now()
        self.last_answer_length = max(0, int(answer_length))
        self.updated_at = _utc_now()

    def observe_signal(
        self, kind: SignalKind, observation: float, alpha: float | None = None
    ) -> Signal:
        """Acumula una observación en la señal (EWMA) y devuelve el nuevo estado."""
        current = self.adaptive_signals.get(kind.value) or Signal(kind=kind)
        updated = current.observe(
            observation, alpha if alpha is not None else DEFAULT_CUTOFFS.ewma_alpha
        )
        self.adaptive_signals[kind.value] = updated
        self.updated_at = _utc_now()
        return updated

    def signals_for_policy(self) -> dict[SignalKind, Signal]:
        """Señales tipadas para `AdaptivePolicy.decide()`.

        Devuelve todas las señales acumuladas; la política es la que descarta
        las observacionales. Así el dashboard y la política leen lo mismo.
        """
        out: dict[SignalKind, Signal] = {}
        for raw, signal in self.adaptive_signals.items():
            try:
                kind = SignalKind(raw)
            except ValueError:
                continue
            out[kind] = signal
        return out

    def mastery_for(self, document_id: UUID) -> float:
        entry = self.mastery_by_document.get(document_id)
        return entry.mastery if entry else 0.0

    def concept_mastery_for(self, concept: str) -> float:
        key = _norm_concept(concept)
        entry = self.mastery_by_concept.get(key)
        return entry.mastery if entry else 0.0

    def has_decision_evidence(self, concept: str) -> bool:
        """Si el concepto tiene evidencia suficiente para decidir en caliente.

        Fuente de verdad única para motor y dificultad: "no medido" y "medido
        en cero" son estados distintos (ADR-006), y un solo auto-reporte no
        convierte lo primero en lo segundo (ADR-007).
        """
        entry = self.mastery_by_concept.get(_norm_concept(concept))
        return entry is not None and entry.informs_decision

    def effective_concept_mastery(self, concept: str, now: datetime | None = None) -> float:
        key = _norm_concept(concept)
        entry = self.mastery_by_concept.get(key)
        return entry.effective_mastery(now) if entry else 0.0

    def record_quiz_result(
        self,
        document_id: UUID,
        score_ratio: float,
        missed_concepts: tuple[str, ...] = (),
        concept_results: tuple[tuple[str, float], ...] = (),
        latency_ms: float | None = None,
        help_level: float = 0.0,
        at: datetime | None = None,
    ) -> None:
        entry = self.mastery_by_document.get(document_id)
        if entry is None:
            entry = DocumentMastery(document_id=document_id)
            self.mastery_by_document[document_id] = entry
        before = entry.mastery
        entry.apply_result(score_ratio)
        self.total_attempts += 1
        deltas = self._apply_graded_items(
            concept_results,
            document_id=document_id,
            latency_ms=latency_ms,
            help_level=help_level,
        )
        self._record_reviews(concept_results, at)
        # Sin conceptos etiquetados, el intento habla por el documento.
        self._track_batch_velocity(deltas, fallback=entry.mastery - before)
        self._cerrar_lote(missed_concepts)

    def level_for_topic(self, topic: str) -> str | None:
        """Nivel alcanzado en un tema, o None si nunca se niveló."""
        return self.level_by_topic.get(_norm_concept(topic))

    def choose_study_goals(self, session_minutes: int | None, daily_goal_minutes: int | None) -> None:
        self.session_minutes = int(session_minutes or 0)
        self.daily_goal_minutes = int(daily_goal_minutes or 0)
        self.updated_at = _utc_now()

    def choose_voice(self, voice: str | None) -> None:
        self.voice_choice = (voice or "").strip().lower()
        self.updated_at = _utc_now()

    def choose_explanation_style(self, style: str | None) -> None:
        """Guarda la elección del estudiante. None o vacío la borra."""
        self.explanation_style_choice = (style or "").strip().lower()
        self.updated_at = _utc_now()

    def label_for_topic(self, topic: str) -> str | None:
        """Cómo mostrar un tema nivelado, o None si no hay etiqueta."""
        return self.topic_labels.get(_norm_concept(topic))

    def record_placement(self, topic: str, level: str, label: str | None = None) -> None:
        """Guarda el veredicto de una ronda de nivelación (ADR-017)."""
        clave = _norm_concept(topic)
        if not clave or not level:
            return
        self.level_by_topic[clave] = level
        if label:
            self.topic_labels[clave] = label
        self.updated_at = _utc_now()

    def record_diagnostic_result(
        self,
        concept_results: tuple[tuple[str, float], ...] = (),
        missed_concepts: tuple[str, ...] = (),
        at: datetime | None = None,
    ) -> None:
        """Ítems calificados de un diagnóstico de entrada, sin documento (ADR-016).

        Misma evidencia que un quiz —son ítems corregidos en servidor, no
        auto-reporte— pero no hay documento cuyo mastery mover. Sin esto, un
        diagnóstico por tema tendría que inventarse un `document_id`, y ese id
        acabaría saliendo en las recomendaciones apuntando a nada.
        """
        self.total_attempts += 1
        deltas = self._apply_graded_items(concept_results, document_id=None)
        self._record_reviews(concept_results, at)
        self._track_batch_velocity(deltas)
        self._cerrar_lote(missed_concepts)

    def _apply_graded_items(
        self,
        concept_results: tuple[tuple[str, float], ...],
        *,
        document_id: UUID | None,
        latency_ms: float | None = None,
        help_level: float = 0.0,
    ) -> list[float]:
        """Aplica ítems calificados a sus conceptos y devuelve los deltas."""
        deltas: list[float] = []
        for concept, ratio in concept_results:
            kind = EvidenceKind.QUIZ_ITEM
            if ratio < 0.5:
                cm = self.mastery_by_concept.get(_norm_concept(concept))
                if cm and cm.error_streak >= 1:
                    kind = EvidenceKind.REPEATED_ERROR
            delta = self._apply_concept_evidence(
                concept,
                EvidenceSample(
                    kind=kind,
                    score_ratio=ratio,
                    document_id=document_id,
                    latency_ms=latency_ms,
                    help_level=help_level,
                ),
            )
            if delta is not None:
                deltas.append(delta)
        return deltas

    def _record_reviews(
        self, concept_results: tuple[tuple[str, float], ...], at: datetime | None
    ) -> None:
        """Un repaso por concepto y por intento, con la nota media de sus ítems (ADR-051)."""
        por_concepto: dict[str, list[float]] = {}
        for concept, ratio in concept_results:
            key = _norm_concept(concept)
            if key and key in self.mastery_by_concept:
                por_concepto.setdefault(key, []).append(float(ratio))
        for key, notas in por_concepto.items():
            self.mastery_by_concept[key].record_review(sum(notas) / len(notas), at)

    def _cerrar_lote(self, missed_concepts: tuple[str, ...]) -> None:
        """Errores, memoria de malentendidos y ritmo: común a quiz y diagnóstico."""
        self._push_errors(missed_concepts)
        for m in missed_concepts:
            self.pedagogical_memory.remember_misconception(m)
        self._update_pace()
        self.updated_at = _utc_now()

    def record_concept_result(
        self,
        concept: str,
        score_ratio: float,
        document_id: UUID | None = None,
    ) -> None:
        self.record_concept_evidence(
            concept,
            EvidenceSample(
                kind=EvidenceKind.QUIZ_ITEM,
                score_ratio=score_ratio,
                document_id=document_id,
            ),
        )

    def record_concept_evidence(self, concept: str, sample: EvidenceSample) -> None:
        """Evidencia de un concepto suelto: una muestra, una observación."""
        delta = self._apply_concept_evidence(concept, sample)
        if delta is not None:
            self._track_velocity(delta)
        self.updated_at = _utc_now()

    def _apply_concept_evidence(
        self, concept: str, sample: EvidenceSample
    ) -> float | None:
        """Aplica la muestra y devuelve el delta de mastery (None si no aplica).

        Devuelve el delta en vez de acumularlo en `learning_velocity` para que
        el llamador decida la granularidad: la velocidad es una observación
        **por evento**, no por concepto etiquetado.
        """
        key = _norm_concept(concept)
        if not key:
            return None
        entry = self.mastery_by_concept.get(key)
        if entry is None:
            entry = ConceptMastery(concept_key=key)
            self.mastery_by_concept[key] = entry
        before = entry.mastery
        entry.apply_evidence(sample)
        # Solo la evidencia calificada escribe el expediente de errores: decir
        # "no entiendo X" es pedir ayuda con X, no fallar X ni malentenderlo de
        # una forma concreta. Antes, preguntar marcaba el concepto como
        # misconception y el motor lo ascendía a diagnóstico (ADR-007).
        if not sample.is_weak_evidence and sample.score_ratio < 0.5:
            self._push_errors((key,))
            self.pedagogical_memory.remember_misconception(key)
        return entry.mastery - before

    def _track_batch_velocity(
        self, deltas: list[float], fallback: float | None = None
    ) -> None:
        """Una observación de velocidad por evento (media de los conceptos).

        Antes la EWMA corría una vez por concepto etiquetado: un quiz de diez
        ítems la dominaba y la velocidad dependía del largo del quiz, no del
        aprendizaje.
        """
        if deltas:
            self._track_velocity(sum(deltas) / len(deltas))
        elif fallback is not None:
            self._track_velocity(fallback)

    def record_ask_struggle(
        self,
        document_id: UUID,
        strength: float = 0.7,
        concepts: tuple[str, ...] = (),
        latency_ms: float | None = None,
        help_level: float = 0.0,
    ) -> None:
        entry = self.mastery_by_document.get(document_id)
        if entry is None:
            entry = DocumentMastery(document_id=document_id)
            self.mastery_by_document[document_id] = entry
        pull = 0.15 + (0.25 * max(0.0, min(1.0, strength)))
        weight = 0.35 + (0.35 * max(0.0, min(1.0, strength)))
        entry.apply_soft_struggle(pull_toward=pull, weight=weight)
        self.total_struggle_signals += 1
        deltas: list[float] = []
        for concept in concepts:
            key = _norm_concept(concept)
            if not key:
                continue
            kind = EvidenceKind.HELP_REQUEST if help_level >= 0.4 else EvidenceKind.ASK_STRUGGLE
            delta = self._apply_concept_evidence(
                key,
                EvidenceSample(
                    kind=kind,
                    score_ratio=max(0.1, 1.0 - strength),
                    weight=0.6 + 0.4 * strength,
                    document_id=document_id,
                    latency_ms=latency_ms,
                    help_level=help_level or (0.5 if kind == EvidenceKind.HELP_REQUEST else 0.0),
                ),
            )
            if delta is not None:
                deltas.append(delta)
        self._track_batch_velocity(deltas)
        # La latencia alta ya viaja en la muestra de arriba (`latency_ms`) y
        # penaliza su ratio. Aquí se emitía además una muestra HIGH_LATENCY
        # sobre los mismos conceptos: el mismo turno contado dos veces.
        # Los conceptos de la pregunta NO entran en `frequent_errors`: la
        # evidencia débil ya quedó registrada en cada `ConceptMastery`, y el
        # foco del motor lee esta lista como "aquí falló" (ADR-007).
        #
        # `pace` tiene un único escritor: `_update_pace`. Aquí se fijaba a
        # "slow" a mano y nada lo recalculaba hasta el siguiente quiz, así que
        # una pregunta dejaba al alumno "lento" indefinidamente — con efecto en
        # dificultad (−0.1) y en estilo (STEP_BY_STEP) (ADR-008).
        self._update_pace()
        self.updated_at = _utc_now()

    def record_conversational_success(
        self,
        document_id: UUID,
        concepts: tuple[str, ...] = (),
        strength: float = 0.6,
    ) -> None:
        """Evidencia POSITIVA desde la conversación (ADR-006, fase 2).

        Antes el chat solo podía empeorar el perfil: `record_ask_struggle` y
        `record_high_latency` eran sus únicas salidas. Quien aprende preguntando
        acumulaba solo evidencia negativa y quedaba atrapado en remediación.

        Pesa menos que un ítem de quiz a propósito: autocorregirse es evidencia
        real pero más débil que acertar un ítem calificado.
        """
        s = max(0.0, min(1.0, float(strength)))
        deltas: list[float] = []
        for concept in concepts:
            key = _norm_concept(concept)
            if not key:
                continue
            delta = self._apply_concept_evidence(
                key,
                EvidenceSample(
                    kind=EvidenceKind.SUCCESS,
                    score_ratio=0.5 + 0.25 * s,
                    weight=0.5 + 0.3 * s,
                    document_id=document_id,
                    is_weak=True,
                ),
            )
            if delta is not None:
                deltas.append(delta)
        self._track_batch_velocity(deltas)
        self.updated_at = _utc_now()

    def record_high_latency(
        self,
        document_id: UUID,
        concepts: tuple[str, ...] = (),
        latency_ms: float = 0.0,
    ) -> None:
        """Señal explícita HIGH_LATENCY (no incrementa struggle).

        La usa el projector cuando el turno fue lento **sin** señal de lucha en
        el texto. Cuando sí la hubo, la latencia viaja dentro de la muestra de
        `record_ask_struggle` y no se emite otra.
        """
        deltas: list[float] = []
        for concept in concepts:
            key = _norm_concept(concept)
            if not key:
                continue
            delta = self._apply_concept_evidence(
                key,
                EvidenceSample(
                    kind=EvidenceKind.HIGH_LATENCY,
                    score_ratio=0.25,
                    weight=0.8,
                    document_id=document_id,
                    latency_ms=latency_ms,
                ),
            )
            if delta is not None:
                deltas.append(delta)
        self._track_batch_velocity(deltas)
        self.updated_at = _utc_now()

    def clear_document(self, document_id: UUID) -> None:
        self.mastery_by_document.pop(document_id, None)
        for cm in self.mastery_by_concept.values():
            if document_id in cm.document_ids:
                cm.document_ids = [d for d in cm.document_ids if d != document_id]
        self.updated_at = _utc_now()

    def weakest_concepts(
        self,
        limit: int = 5,
        document_id: UUID | None = None,
        *,
        use_effective: bool = True,
        now: datetime | None = None,
    ) -> list[str]:
        items = list(self.mastery_by_concept.values())
        if document_id is not None:
            items = [c for c in items if document_id in c.document_ids or not c.document_ids]

        def rank(c: ConceptMastery) -> tuple[float, int]:
            m = c.effective_mastery(now) if use_effective else c.mastery
            return (m, -c.attempts)

        ranked = sorted(items, key=rank)
        return [c.concept_key for c in ranked[:limit]]

    def effective_mastery_by_concept(
        self, now: datetime | None = None
    ) -> dict[str, float]:
        """Mastery efectivo de cada concepto conocido, como lectura.

        Lo consumen las vistas que derivan progreso (p. ej. la ruta de
        aprendizaje): el perfil es la única fuente de verdad del mastery, así
        que nadie más lo almacena ni lo declara (ADR-008).
        """
        return {
            key: entry.effective_mastery(now)
            for key, entry in self.mastery_by_concept.items()
        }

    def forgotten_concepts(self, limit: int = 5, min_gap: float = 0.15) -> list[str]:
        ranked = sorted(
            self.mastery_by_concept.values(),
            key=lambda c: c.forgetting_gap(),
            reverse=True,
        )
        return [c.concept_key for c in ranked if c.forgetting_gap() >= min_gap][:limit]

    def pending_celebration(self, limit: int = 20) -> str | None:
        """Concepto dominado que aún no se le ha reconocido, o None.

        El hito reutiliza los umbrales ya calibrados de `mastered_concepts`
        (mastery efectivo ≥ 0.8 y confianza ≥ 0.55): cruzar a dominado es el
        logro, y se reconoce una sola vez (ADR-009).
        """
        for key in self.mastered_concepts(limit=limit):
            if key not in self.celebrated_concepts:
                return key
        return None

    def mark_celebrated(self, concept: str) -> None:
        key = _norm_concept(concept)
        if not key or key in self.celebrated_concepts:
            return
        self.celebrated_concepts.append(key)
        self.updated_at = _utc_now()

    def mastered_concepts(
        self, limit: int = 5, min_mastery: float = 0.8, min_confidence: float = 0.55
    ) -> list[str]:
        items = [
            c
            for c in self.mastery_by_concept.values()
            if c.effective_mastery() >= min_mastery and c.confidence >= min_confidence
        ]
        ranked = sorted(items, key=lambda c: (c.effective_mastery(), c.confidence), reverse=True)
        return [c.concept_key for c in ranked[:limit]]

    def _push_errors(self, concepts: tuple[str, ...]) -> None:
        for concept in concepts:
            label = _norm_concept(concept)
            if not label:
                continue
            if label in self.frequent_errors:
                self.frequent_errors.remove(label)
            self.frequent_errors.insert(0, label)
        self.frequent_errors = self.frequent_errors[:20]

    def _track_velocity(self, delta: float) -> None:
        self.learning_velocity = 0.3 * delta + 0.7 * self.learning_velocity

    def _update_pace(self) -> None:
        if self.total_attempts <= 1 and self.total_struggle_signals == 0:
            self.pace = "steady"
            return
        # Solo los documentos con intentos calificados hablan del ritmo: un
        # mastery de documento que solo bajó por señales de struggle es
        # auto-reporte, no medición (ADR-007).
        measured = [m for m in self.mastery_by_document.values() if m.attempts > 0]
        weak = sum(1 for m in measured if m.mastery < 0.4)
        strong = sum(1 for m in measured if m.mastery >= 0.7)
        if self.learning_velocity < -0.05 or weak > strong:
            self.pace = "slow"
        elif self.learning_velocity > 0.08 and strong > weak and self.total_attempts >= 3:
            self.pace = "fast"
        else:
            self.pace = "steady"

    def weakest_documents(self, limit: int = 3) -> list[UUID]:
        ranked = sorted(
            self.mastery_by_document.values(),
            key=lambda m: (m.mastery, -m.attempts),
        )
        return [m.document_id for m in ranked[:limit]]
