"""Memoria adaptativa por concepto: cuándo repasar y cuánto se recuerda (ADR-051).

El olvido ya era exponencial (ADR-003), pero con la misma vida media para todo y
para todos: 14 días. Aquí la vida media de cada concepto se ajusta con cada repaso
calificado, en la línea de FSRS y de la half-life regression de Duolingo:

- **Acertar cuando ya costaba recordar** alarga mucho la vida media: es el efecto
  del espaciado y de la recuperación difícil.
- **Acertar justo después de estudiar** casi no la mueve: repetir en bloque no
  consolida.
- **Fallar** la acorta: hay que volver antes.

Lo que sale de aquí es una **estimación** del modelo, no una medición de la memoria
del estudiante. Lo medido es el resultado de cada repaso; la curva entre repasos
es la fórmula. El cliente debe presentarlas así.

Puro y determinista: los números entran inyectados, no se leen del entorno.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import exp, log, log2

#: Vida media con la que nace un concepto (ADR-003).
INITIAL_HALF_LIFE_DAYS = 14.0
#: Por debajo de un día el modelo dejaría de tener sentido a la escala de una
#: plataforma que se abre una vez al día; por encima de un año, igual.
MIN_HALF_LIFE_DAYS = 1.0
MAX_HALF_LIFE_DAYS = 365.0
#: Desde aquí un repaso cuenta como recordado. Hipótesis nombrada, como los
#: cutoffs del ADR-004: es el mismo listón que aprobar una comprobación.
RECALL_THRESHOLD = 0.6
#: Cuánto crece la vida media con un acierto que costó (recuerdo estimado bajo).
#: Con 3, repasar al 90 % de recuerdo la multiplica por 1,3; al 50 %, por 2,5.
SUCCESS_GAIN = 3.0
#: Retención que se quiere mantener: el próximo repaso cae cuando la estimación
#: baja de aquí. 0,9 es el valor por defecto de FSRS.
DEFAULT_DESIRED_RETENTION = 0.9
#: Cuántos repasos se guardan por concepto: bastan para dibujar la curva.
MAX_REVIEW_LOG = 30


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _days(desde: datetime, hasta: datetime) -> float:
    return max(0.0, (_utc(hasta) - _utc(desde)).total_seconds() / 86400.0)


def retention(elapsed_days: float, half_life_days: float) -> float:
    """Recuerdo estimado: 0,5 ** (días / vida media)."""
    h = max(MIN_HALF_LIFE_DAYS, float(half_life_days))
    return exp(-log(2.0) * max(0.0, elapsed_days) / h)


def interval_days(half_life_days: float, desired_retention: float = DEFAULT_DESIRED_RETENTION) -> float:
    """Días hasta que el recuerdo estimado baja a `desired_retention`."""
    objetivo = min(0.99, max(0.5, float(desired_retention)))
    return max(MIN_HALF_LIFE_DAYS, float(half_life_days)) * log2(1.0 / objetivo)


def first_half_life(score_ratio: float) -> float:
    """El primer repaso calificado fija el punto de partida.

    Sin historia, la nota es lo único que hay: 0 → 7 días, 1 → 21 días.
    """
    r = max(0.0, min(1.0, score_ratio))
    return _acotar(INITIAL_HALF_LIFE_DAYS * (0.5 + r))


def next_half_life(half_life_days: float, elapsed_days: float, score_ratio: float) -> float:
    """La vida media tras un repaso, a partir de cuánto se esperaba recordar."""
    h = max(MIN_HALF_LIFE_DAYS, float(half_life_days))
    r = max(0.0, min(1.0, score_ratio))
    esperado = retention(elapsed_days, h)
    if r >= RECALL_THRESHOLD:
        # Cuanto menos se esperaba recordar, más vale haberlo recordado.
        return _acotar(h * (1.0 + SUCCESS_GAIN * (1.0 - esperado) * r))
    # Fallar con nota parcial acorta menos que fallar en blanco.
    return _acotar(h * (0.3 + 0.5 * r))


def _acotar(h: float) -> float:
    return max(MIN_HALF_LIFE_DAYS, min(MAX_HALF_LIFE_DAYS, h))


@dataclass(frozen=True)
class ReviewEntry:
    """Un repaso calificado: lo medido, y la vida media que dejó."""

    at: datetime
    score_ratio: float
    half_life_days: float


def next_review_at(
    last_reviewed_at: datetime, half_life_days: float, desired_retention: float = DEFAULT_DESIRED_RETENTION
) -> datetime:
    return _utc(last_reviewed_at) + timedelta(days=interval_days(half_life_days, desired_retention))


#: Puntos de la curva estimada: uno al día da de sobra para dibujarla.
MAX_CURVE_POINTS = 60


def estimated_curve(
    log_: list[ReviewEntry],
    until: datetime,
    *,
    max_points: int = MAX_CURVE_POINTS,
) -> list[tuple[datetime, float]]:
    """La curva estimada, tramo a tramo: cada repaso la devuelve a 1 con su vida media.

    Volver a 1 tras un repaso es una simplificación: después de corregir, el
    estudiante ve la respuesta buena, así que el recuerdo inmediato es alto
    aunque haya fallado. Lo que cambia con el fallo es lo rápido que cae.

    Cada tramo lleva al menos su inicio y su final (el salto de cada repaso tiene
    que verse); si no caben todos, se dibujan los más recientes.
    """
    if not log_:
        return []
    entradas = sorted(log_, key=lambda e: _utc(e.at))
    minimo_por_tramo = 3
    caben = max(1, max_points // minimo_por_tramo)
    entradas = entradas[-caben:]
    por_tramo = max(minimo_por_tramo, max_points // len(entradas))
    puntos: list[tuple[datetime, float]] = []
    for i, e in enumerate(entradas):
        inicio = _utc(e.at)
        fin = _utc(entradas[i + 1].at) if i + 1 < len(entradas) else max(inicio, _utc(until))
        total = _days(inicio, fin)
        if total == 0.0:
            puntos.append((inicio, 1.0))
            continue
        n = por_tramo - 1
        for k in range(n + 1):
            d = total * k / n
            puntos.append((inicio + timedelta(days=d), retention(d, e.half_life_days)))
    return puntos[:max_points]
