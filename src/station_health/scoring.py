"""The scoring core: a Station's Health Reports in the Scoring Window → its Hygiene Score.

Pure: no Flask, no database. See "Scoring formula" in the spec.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ScoringConfig:
    # The latency score falls linearly from 1.0 at `latency_good_ms` to 0.0 at `latency_bad_ms`.
    latency_good_ms: float = 150
    latency_bad_ms: float = 1000
    # The error score falls linearly from 1.0 at 0 errors per online Health Report to 0.0 here.
    error_limit: float = 3
    # Weights of the latency and error scores in the quality blend.
    latency_weight: float = 0.4
    error_weight: float = 0.6


@dataclass(frozen=True)
class WindowReport:
    """The parts of one Health Report in the Scoring Window that scoring uses."""

    online: bool
    latency_ms: float
    error_count: int


@dataclass(frozen=True)
class StationScore:
    """A Station's Hygiene Score (0-100) and the parts it was computed from.

    With no online Health Reports in the window, latency and errors were never
    measured: their scores are None and the Hygiene Score is 0.
    """

    hygiene_score: int
    availability: float
    latency_score: float | None
    error_score: float | None
    p95_latency_ms: float | None


def score_station(reports: Sequence[WindowReport], config: ScoringConfig) -> StationScore:
    """Score one Station from its (non-empty) Health Reports in the Scoring Window."""
    online_reports = [report for report in reports if report.online]
    availability = len(online_reports) / len(reports)
    if not online_reports:
        return StationScore(
            hygiene_score=0,
            availability=availability,
            latency_score=None,
            error_score=None,
            p95_latency_ms=None,
        )
    p95_latency_ms = p95([report.latency_ms for report in online_reports])
    latency_score = _falling_linear(p95_latency_ms, config.latency_good_ms, config.latency_bad_ms)
    # Only online Health Reports carry meaningful errors, as they do latency.
    errors_per_online_report = sum(r.error_count for r in online_reports) / len(online_reports)
    error_score = _falling_linear(errors_per_online_report, 0, config.error_limit)
    quality = config.latency_weight * latency_score + config.error_weight * error_score
    return StationScore(
        hygiene_score=_round_half_up(availability * quality * 100),
        availability=availability,
        latency_score=latency_score,
        error_score=error_score,
        p95_latency_ms=p95_latency_ms,
    )


def p95(values: Sequence[float]) -> float:
    """The nearest-rank 95th percentile: always one of the observed values."""
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def _round_half_up(value: float) -> int:
    """12.5 → 13, unlike Python's `round`. Float noise (62.4999999) is rounded away first."""
    return math.floor(round(value, 9) + 0.5)


def _falling_linear(value: float, best: float, worst: float) -> float:
    """1.0 at or below `best`, 0.0 at or above `worst`, linear in between."""
    return min(1.0, max(0.0, (worst - value) / (worst - best)))
