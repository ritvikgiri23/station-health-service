"""The scoring core: a Station's Health Reports in the Scoring Window → its Hygiene Score,
and with its previous flag state → whether it has Poor Hygiene.

Pure: no Flask, no database. See "Scoring formula" in the spec.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


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
    # A Station enters Poor Hygiene below `flag_threshold`, and leaves it only at or above
    # `clear_threshold` with at least `min_reports_to_clear` Health Reports in the window.
    flag_threshold: int = 60
    clear_threshold: int = 70
    min_reports_to_clear: int = 5


class FlagReason(StrEnum):
    SILENT = "silent"
    AVAILABILITY = "availability"
    LATENCY = "latency"
    ERRORS = "errors"


class FlagDirection(StrEnum):
    ENTERED = "entered"
    LEFT = "left"


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


@dataclass(frozen=True)
class FlagState:
    """Whether a Station has Poor Hygiene, why, and since when (both None when it has not)."""

    poor_hygiene: bool
    flag_reason: FlagReason | None = None
    flagged_since: datetime | None = None


NOT_FLAGGED = FlagState(poor_hygiene=False)


@dataclass(frozen=True)
class FlagChange:
    """A Station entering or leaving Poor Hygiene.

    Leaving carries the Flag Reason the Station last had while flagged.
    """

    direction: FlagDirection
    flag_reason: FlagReason


@dataclass(frozen=True)
class Assessment:
    """One Station's judgement in one scoring run."""

    # None when the Station is Silent: with no Health Reports there is nothing to score.
    score: StationScore | None
    report_count: int
    flag: FlagState
    flag_change: FlagChange | None

    @property
    def silent(self) -> bool:
        return self.score is None


def assess_station(
    reports: Sequence[WindowReport], previous: FlagState, now: datetime, config: ScoringConfig
) -> Assessment:
    """Score one Station from its Health Reports in the Scoring Window and decide its flag.

    No Health Reports means Silent, which is always Poor Hygiene. Flagging is quick (below
    the Flag Threshold); clearing must be earned (Clear Threshold and minimum evidence).
    """
    score = score_station(reports, config) if reports else None
    if score is None:
        reason = FlagReason.SILENT
        poor_hygiene = True
    else:
        reason = flag_reason(score)
        if previous.poor_hygiene:
            poor_hygiene = (
                score.hygiene_score < config.clear_threshold
                or len(reports) < config.min_reports_to_clear
            )
        else:
            poor_hygiene = score.hygiene_score < config.flag_threshold

    if poor_hygiene:
        flag = FlagState(
            poor_hygiene=True,
            flag_reason=reason,
            flagged_since=previous.flagged_since if previous.poor_hygiene else now,
        )
    else:
        flag = NOT_FLAGGED

    change = None
    if poor_hygiene and not previous.poor_hygiene:
        change = FlagChange(FlagDirection.ENTERED, reason)
    elif previous.poor_hygiene and not poor_hygiene:
        # A flagged Station always has a Flag Reason.
        assert previous.flag_reason is not None
        change = FlagChange(FlagDirection.LEFT, previous.flag_reason)
    return Assessment(score=score, report_count=len(reports), flag=flag, flag_change=change)


def flag_reason(score: StationScore) -> FlagReason:
    """Whichever of Availability, latency score and error score is lowest.

    Ties go to the first in that order. Unmeasured latency and errors (no online Health
    Reports) mean Availability is 0, so Availability is the reason.
    """
    parts = [
        (FlagReason.AVAILABILITY, score.availability),
        (FlagReason.LATENCY, score.latency_score),
        (FlagReason.ERRORS, score.error_score),
    ]
    return min(
        ((reason, value) for reason, value in parts if value is not None), key=lambda p: p[1]
    )[0]


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
