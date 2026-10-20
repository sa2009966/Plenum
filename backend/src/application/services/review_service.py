"""Agenda de repasos y curva del olvido de cada concepto (ADR-051).

Solo lee: el perfil lo escribe el projector (invariante 1). Aquí se decide qué
toca repasar y cuándo, con el modelo de `memory_model`, y se separa lo medido
(repasos calificados) de lo estimado (la curva entre repasos).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from src.application.services.study_time_service import zona
from src.domain import memory_model
from src.domain.aggregates.student_profile import ConceptMastery
from src.domain.catalog.prerequisite_seeds import seed_display_labels
from src.domain.concept_identity import canonicalize_concept
from src.domain.memory_model import ReviewEntry
from src.domain.ports.repositories import LearningPathRepository, StudentProfileRepository

ESTIMATE_NOTE = "Estimación del modelo de olvido, no una medición de tu memoria."


class ConceptWithoutReviews(LookupError):
    pass


@dataclass(frozen=True)
class ReviewItem:
    concept: str
    label: str
    status: str  # overdue | today | upcoming
    estimated_retention: float
    next_review_at: datetime
    last_reviewed_at: datetime
    half_life_days: float
    reviews: int
    mastery: float
    path_id: UUID | None


@dataclass(frozen=True)
class ReviewAgenda:
    generated_at: datetime
    desired_retention: float
    counts: dict[str, int]
    items: list[ReviewItem]


@dataclass(frozen=True)
class RetentionCurve:
    concept: str
    label: str
    desired_retention: float
    half_life_days: float
    next_review_at: datetime
    measured: list[tuple[datetime, float]]
    estimated: list[tuple[datetime, float]]
    note: str = ESTIMATE_NOTE


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _desde(c: ConceptMastery) -> datetime | None:
    """Desde cuándo cae el recuerdo de este concepto, o None si no hay medición.

    Perfiles anteriores al ADR-051 no traen historial de repasos: se toma la última
    práctica, que es una fecha real, siempre que el concepto tenga evidencia
    calificada. Sin ella no se agenda nada (invariante 3: no medido ≠ cero).
    """
    if c.last_reviewed_at is not None:
        return _aware(c.last_reviewed_at)
    if c.measured_evidence_count > 0 and c.informs_decision and c.last_practiced_at is not None:
        return _aware(c.last_practiced_at)
    return None


class ReviewScheduleService:
    def __init__(
        self,
        profile_repository: StudentProfileRepository,
        path_repository: LearningPathRepository,
        desired_retention: float = memory_model.DEFAULT_DESIRED_RETENTION,
    ) -> None:
        self._profiles = profile_repository
        self._paths = path_repository
        self._retencion = desired_retention

    async def _contexto(self, user_id: UUID):
        perfil = await self._profiles.find_by_student(user_id)
        rutas = await self._paths.find_by_owner(user_id)
        semillas = seed_display_labels()

        def mayuscula(texto: str) -> str:
            return texto[:1].upper() + texto[1:]

        def ruta_y_titulo(clave: str) -> tuple[UUID | None, str]:
            for ruta in rutas:
                modulo = ruta.module(clave)
                if modulo is not None:
                    return ruta.id, mayuscula(modulo.title or semillas.get(clave, clave))
            etiqueta = (perfil.topic_labels.get(clave) if perfil else None) or semillas.get(clave) or clave
            return None, mayuscula(etiqueta)

        return perfil, ruta_y_titulo

    async def agenda(
        self, user_id: UUID, tz: str | None = None, limit: int = 50, now: datetime | None = None
    ) -> ReviewAgenda:
        ahora = _aware(now or datetime.now(timezone.utc))
        perfil, ruta_y_titulo = await self._contexto(user_id)
        local = ahora.astimezone(zona(tz))
        hoy = local.replace(hour=0, minute=0, second=0, microsecond=0)
        manana = hoy + timedelta(days=1)

        items: list[ReviewItem] = []
        for clave, c in (perfil.mastery_by_concept.items() if perfil else []):
            desde = _desde(c)
            if desde is None:
                continue
            proximo = memory_model.next_review_at(desde, c.half_life_days, self._retencion)
            proximo_local = proximo.astimezone(local.tzinfo)
            estado = "overdue" if proximo_local < hoy else "today" if proximo_local < manana else "upcoming"
            dias = max(0.0, (ahora - desde).total_seconds() / 86400.0)
            path_id, etiqueta = ruta_y_titulo(clave)
            items.append(
                ReviewItem(
                    concept=clave,
                    label=etiqueta,
                    status=estado,
                    estimated_retention=round(memory_model.retention(dias, c.half_life_days), 3),
                    next_review_at=proximo,
                    last_reviewed_at=desde,
                    half_life_days=round(c.half_life_days, 2),
                    reviews=len(c.review_log),
                    mastery=round(max(0.0, min(1.0, c.mastery)), 3),
                    path_id=path_id,
                )
            )

        orden = {"overdue": 0, "today": 1, "upcoming": 2}
        # Lo pendiente, del que menos se recuerda al que más; lo próximo, por fecha.
        items.sort(
            key=lambda i: (
                orden[i.status],
                i.estimated_retention if i.status != "upcoming" else 0.0,
                i.next_review_at,
            )
        )
        counts = {k: sum(1 for i in items if i.status == k) for k in orden}
        return ReviewAgenda(ahora, self._retencion, counts, items[: max(0, limit)])

    async def curve(self, user_id: UUID, concept: str, now: datetime | None = None) -> RetentionCurve:
        ahora = _aware(now or datetime.now(timezone.utc))
        perfil, ruta_y_titulo = await self._contexto(user_id)
        clave = canonicalize_concept(concept)
        c = perfil.mastery_by_concept.get(clave) if perfil else None
        desde = _desde(c) if c else None
        if c is None or desde is None:
            raise ConceptWithoutReviews(clave)
        proximo = memory_model.next_review_at(desde, c.half_life_days, self._retencion)
        # Sin historial (perfil antiguo), la curva arranca en la última práctica y
        # no hay puntos medidos que enseñar.
        tramos = list(c.review_log) or [ReviewEntry(at=desde, score_ratio=0.0, half_life_days=c.half_life_days)]
        hasta = max(ahora, proximo) + timedelta(days=max(1.0, c.half_life_days * 0.25))
        _, etiqueta = ruta_y_titulo(clave)
        return RetentionCurve(
            concept=clave,
            label=etiqueta,
            desired_retention=self._retencion,
            half_life_days=round(c.half_life_days, 2),
            next_review_at=proximo,
            measured=[(_aware(e.at), e.score_ratio) for e in sorted(c.review_log, key=lambda e: _aware(e.at))],
            estimated=[(t, round(r, 4)) for t, r in memory_model.estimated_curve(tramos, hasta)],
        )
