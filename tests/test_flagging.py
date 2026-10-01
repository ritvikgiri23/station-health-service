"""The pure scoring core's flagging: Poor Hygiene, Silent, Flag Reason and Flag Changes."""

from datetime import timedelta

import pytest

from station_health.scoring import (
    NOT_FLAGGED,
    FlagChange,
    FlagDirection,
    FlagReason,
    FlagState,
    ScoringConfig,
    WindowReport,
    assess_station,
)
from tests.support import START

DEFAULTS = ScoringConfig()


def online(latency_ms: float = 100, error_count: int = 0) -> WindowReport:
    return WindowReport(online=True, latency_ms=latency_ms, error_count=error_count)


def offline() -> WindowReport:
    return WindowReport(online=False, latency_ms=5000, error_count=0)


def scoring(score: int) -> list[WindowReport]:
    """100 Health Reports, `score` of them online and perfect: the Hygiene Score is `score`."""
    return [online()] * score + [offline()] * (100 - score)


def test_a_score_below_the_flag_threshold_enters_poor_hygiene() -> None:
    assessment = assess_station(scoring(59), NOT_FLAGGED, START, DEFAULTS)

    assert assessment.score is not None
    assert assessment.score.hygiene_score == 59
    assert assessment.flag.poor_hygiene
    assert assessment.flag.flag_reason is FlagReason.AVAILABILITY
    assert assessment.flag.flagged_since == START
    assert assessment.flag_change is not None
    assert assessment.flag_change.direction is FlagDirection.ENTERED
    assert assessment.flag_change.flag_reason is FlagReason.AVAILABILITY


def test_a_score_at_the_flag_threshold_does_not_flag() -> None:
    assessment = assess_station(scoring(60), NOT_FLAGGED, START, DEFAULTS)

    assert not assessment.flag.poor_hygiene
    assert assessment.flag.flag_reason is None
    assert assessment.flag.flagged_since is None
    assert assessment.flag_change is None


def test_hovering_between_the_thresholds_stays_flagged() -> None:
    # 58 flags; 61, 59 and 62 are all below the Clear Threshold, so nothing flickers.
    state = NOT_FLAGGED
    changes = []
    for minute, score in enumerate([58, 61, 59, 62]):
        assessment = assess_station(
            scoring(score), state, START + timedelta(minutes=minute), DEFAULTS
        )
        state = assessment.flag
        changes.append(assessment.flag_change)

    assert state.poor_hygiene
    assert state.flagged_since == START
    assert changes[0] is not None
    assert changes[1:] == [None, None, None]


FLAGGED = FlagState(
    poor_hygiene=True, flag_reason=FlagReason.AVAILABILITY, flagged_since=START - timedelta(hours=1)
)


def test_reaching_the_clear_threshold_with_enough_health_reports_leaves_poor_hygiene() -> None:
    assessment = assess_station(scoring(70), FLAGGED, START, DEFAULTS)

    assert assessment.flag == NOT_FLAGGED
    assert assessment.flag_change is not None
    assert assessment.flag_change.direction is FlagDirection.LEFT
    # Leaving records why the Station had been flagged.
    assert assessment.flag_change.flag_reason is FlagReason.AVAILABILITY


@pytest.mark.parametrize(("report_count", "cleared"), [(4, False), (5, True)])
def test_clearing_needs_the_minimum_number_of_health_reports(
    report_count: int, cleared: bool
) -> None:
    assessment = assess_station([online()] * report_count, FLAGGED, START, DEFAULTS)

    assert assessment.flag.poor_hygiene is not cleared


def test_the_thresholds_and_minimum_evidence_are_configurable() -> None:
    config = ScoringConfig(flag_threshold=40, clear_threshold=50, min_reports_to_clear=2)

    assert not assess_station(scoring(45), NOT_FLAGGED, START, config).flag.poor_hygiene
    assert assess_station(scoring(39), NOT_FLAGGED, START, config).flag.poor_hygiene
    assert not assess_station(scoring(50), FLAGGED, START, config).flag.poor_hygiene
    assert not assess_station([online()] * 2, FLAGGED, START, config).flag.poor_hygiene


def test_a_station_with_no_health_reports_is_silent_and_has_poor_hygiene() -> None:
    assessment = assess_station([], NOT_FLAGGED, START, DEFAULTS)

    assert assessment.silent
    assert assessment.score is None
    assert assessment.report_count == 0
    assert assessment.flag == FlagState(
        poor_hygiene=True, flag_reason=FlagReason.SILENT, flagged_since=START
    )
    assert assessment.flag_change == FlagChange(FlagDirection.ENTERED, FlagReason.SILENT)


def test_a_flagged_station_going_silent_stays_flagged_since_it_was_first_flagged() -> None:
    assessment = assess_station([], FLAGGED, START, DEFAULTS)

    assert assessment.flag == FlagState(
        poor_hygiene=True, flag_reason=FlagReason.SILENT, flagged_since=FLAGGED.flagged_since
    )
    assert assessment.flag_change is None


def test_one_health_report_after_silence_ends_silent_but_stays_flagged() -> None:
    silent = assess_station([], NOT_FLAGGED, START, DEFAULTS).flag

    assessment = assess_station([online()], silent, START + timedelta(minutes=1), DEFAULTS)

    assert not assessment.silent
    assert assessment.score is not None
    assert assessment.score.hygiene_score == 100
    assert assessment.flag.poor_hygiene
    # No longer Silent, so not flagged as Silent: every part ties at 1.0.
    assert assessment.flag.flag_reason is FlagReason.AVAILABILITY
    assert assessment.flag.flagged_since == START
    assert assessment.flag_change is None


def test_a_flagged_station_takes_the_flag_reason_of_its_current_score() -> None:
    # Errors are now the lowest part (error score 1/3); 60 is still below the Clear Threshold.
    assessment = assess_station([online(error_count=2)] * 10, FLAGGED, START, DEFAULTS)

    assert assessment.score is not None
    assert assessment.score.hygiene_score == 60
    assert assessment.flag.poor_hygiene
    assert assessment.flag.flag_reason is FlagReason.ERRORS
    assert assessment.flag.flagged_since == FLAGGED.flagged_since


@pytest.mark.parametrize(
    ("reports", "reason"),
    [
        pytest.param(scoring(50), FlagReason.AVAILABILITY, id="availability lowest"),
        # Latency score 0.0 alone leaves a reliable Station at 60, so add an Offline report.
        pytest.param(
            [online(latency_ms=1000)] * 9 + [offline()], FlagReason.LATENCY, id="latency lowest"
        ),
        pytest.param([online(error_count=3)] * 10, FlagReason.ERRORS, id="errors lowest"),
        pytest.param([offline()] * 10, FlagReason.AVAILABILITY, id="nothing measured online"),
        # Availability 0.5, latency score 0.5 (575 ms), error score 0.5 (1.5 per online report).
        pytest.param(
            [online(latency_ms=575, error_count=n % 2 * 3) for n in range(10)] + [offline()] * 10,
            FlagReason.AVAILABILITY,
            id="three-way tie goes to availability",
        ),
        # Latency score 0.5 and error score 0.5, both below Availability 1.0.
        pytest.param(
            [online(latency_ms=575, error_count=n % 2 * 3) for n in range(10)],
            FlagReason.LATENCY,
            id="latency and errors tie goes to latency",
        ),
    ],
)
def test_the_flag_reason_is_the_lowest_part_of_the_score(
    reports: list[WindowReport], reason: FlagReason
) -> None:
    assessment = assess_station(reports, NOT_FLAGGED, START, DEFAULTS)

    assert assessment.flag.poor_hygiene
    assert assessment.flag.flag_reason is reason
