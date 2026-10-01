"""The pure hourly summary: one Station's Health Reports in one hour → its summary figures.

The hour is [start, start + 1h). Its average Hygiene Score is the mean of the Hygiene
Scores of the consecutive Scoring Windows that tile it, each scored by the scoring core
(the last one shorter when the window does not divide the hour). A window with no Health
Reports is Silent, which counts as 0, as it does in the Poor Hygiene list (ADR-0002).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import fmean

from station_health.scoring import ScoringConfig, WindowReport, p95, score_station

HOUR = timedelta(hours=1)


def floor_hour(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


@dataclass(frozen=True)
class TimedReport:
    timestamp: datetime
    report: WindowReport


@dataclass(frozen=True)
class HourFigures:
    report_count: int
    online_count: int
    # Over online Health Reports, as in scoring; None when none was online.
    average_latency_ms: float | None
    max_latency_ms: float | None
    p95_latency_ms: float | None
    # The Error Counts of every Health Report, added up.
    error_count_sum: int
    average_hygiene_score: float


def summarise_hour(
    reports: Sequence[TimedReport],
    hour_start: datetime,
    scoring_window: timedelta,
    config: ScoringConfig,
) -> HourFigures:
    """Summarise one Station's (non-empty) Health Reports timestamped within the hour."""
    latencies = [r.report.latency_ms for r in reports if r.report.online]
    return HourFigures(
        report_count=len(reports),
        online_count=len(latencies),
        average_latency_ms=fmean(latencies) if latencies else None,
        max_latency_ms=max(latencies) if latencies else None,
        p95_latency_ms=p95(latencies) if latencies else None,
        error_count_sum=sum(r.report.error_count for r in reports),
        average_hygiene_score=fmean(
            score_station(window, config).hygiene_score if window else 0
            for window in _windows(reports, hour_start, scoring_window)
        ),
    )


def _windows(
    reports: Sequence[TimedReport], hour_start: datetime, scoring_window: timedelta
) -> list[list[WindowReport]]:
    """The hour's Health Reports split into consecutive Scoring Windows, [start, end)."""
    count = -(-HOUR // scoring_window)  # ceiling division
    windows: list[list[WindowReport]] = [[] for _ in range(count)]
    for timed in reports:
        windows[(timed.timestamp - hour_start) // scoring_window].append(timed.report)
    return windows
