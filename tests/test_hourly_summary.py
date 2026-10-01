"""The pure hourly summary: one Station's Health Reports in one hour → its summary figures."""

from datetime import UTC, datetime, timedelta

import pytest

from station_health.scoring import ScoringConfig, WindowReport
from station_health.summaries.summarise import HourFigures, TimedReport, summarise_hour

DEFAULTS = ScoringConfig()
HOUR = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
WINDOW = timedelta(minutes=15)


def at(
    minute: float, online: bool = True, latency_ms: float = 100, error_count: int = 0
) -> TimedReport:
    return TimedReport(
        timestamp=HOUR + timedelta(minutes=minute),
        report=WindowReport(online=online, latency_ms=latency_ms, error_count=error_count),
    )


def test_counts_latency_and_errors_over_the_hour() -> None:
    reports = [at(m, latency_ms=10 * (m + 1), error_count=1) for m in range(20)]
    reports += [at(20 + m, online=False, latency_ms=5000, error_count=2) for m in range(5)]

    figures = summarise_hour(reports, HOUR, WINDOW, DEFAULTS)

    assert figures.report_count == 25
    assert figures.online_count == 20
    # Latency figures are over online Health Reports, as in scoring: an Offline one's
    # latency is the Probe's timeout.
    assert figures.average_latency_ms == pytest.approx(105)
    assert figures.max_latency_ms == 200
    assert figures.p95_latency_ms == 190
    assert figures.error_count_sum == 20 + 10


def test_the_average_hygiene_score_is_over_the_scoring_windows_that_tile_the_hour() -> None:
    # Window 1 (:00-:15): healthy, 100. Window 2 (:15-:30): half Offline, 50.
    # Window 3 (:30-:45): no Health Reports, so Silent, which counts as 0. Window 4: all
    # Offline, 0.
    reports = [at(m) for m in range(0, 15, 3)]
    reports += [at(15 + m, online=m % 2 == 0) for m in range(4)]
    reports += [at(45 + m, online=False) for m in range(3)]

    figures = summarise_hour(reports, HOUR, WINDOW, DEFAULTS)

    assert figures.average_hygiene_score == pytest.approx((100 + 50 + 0 + 0) / 4)


def test_a_window_boundary_belongs_to_the_later_window() -> None:
    # At exactly :15 the Health Report starts window 2, leaving window 1 healthy.
    reports = [at(0), at(15, online=False), at(30), at(45)]

    figures = summarise_hour(reports, HOUR, WINDOW, DEFAULTS)

    assert figures.average_hygiene_score == pytest.approx((100 + 0 + 100 + 100) / 4)


def test_a_scoring_window_that_does_not_divide_the_hour_ends_with_a_short_window() -> None:
    # 25-minute windows: :00-:25, :25-:50, and :50-:60.
    reports = [at(0), at(26, online=False), at(55)]

    figures = summarise_hour(reports, HOUR, timedelta(minutes=25), DEFAULTS)

    assert figures.average_hygiene_score == pytest.approx((100 + 0 + 100) / 3)


def test_an_hour_offline_throughout_has_no_latency_figures() -> None:
    figures = summarise_hour([at(m, online=False) for m in range(5)], HOUR, WINDOW, DEFAULTS)

    assert figures == HourFigures(
        report_count=5,
        online_count=0,
        average_latency_ms=None,
        max_latency_ms=None,
        p95_latency_ms=None,
        error_count_sum=0,
        average_hygiene_score=0,
    )
