"""The pure scoring core: a Station's Health Reports in the Scoring Window → its Hygiene Score."""

import pytest

from station_health.scoring import ScoringConfig, WindowReport, score_station

DEFAULTS = ScoringConfig()


def online(latency_ms: float = 100, error_count: int = 0) -> WindowReport:
    return WindowReport(online=True, latency_ms=latency_ms, error_count=error_count)


def offline(latency_ms: float = 5000, error_count: int = 0) -> WindowReport:
    return WindowReport(online=False, latency_ms=latency_ms, error_count=error_count)


# The scoring scenarios from the spec. Expected values are worked by hand from the formula:
# score = Availability x (0.4 x latency score + 0.6 x error score) x 100.
SCENARIOS = [
    pytest.param(
        [online()] * 15,
        (1.0, 1.0, 1.0, 100),
        id="healthy",
    ),
    pytest.param(
        # Fine whenever it answers, but 6 of 15 Probes found it Offline.
        [online(), offline()] * 6 + [online()] * 3,
        (0.6, 1.0, 1.0, 60),
        id="flapping",
    ),
    pytest.param(
        # Latency score (1000 - 800) / 850; 0.4 x 0.235 + 0.6 = 0.694.
        [online(latency_ms=800)] * 15,
        (1.0, 4 / 17, 1.0, 69),
        id="slow but reliable",
    ),
    pytest.param(
        # 2 errors per online Health Report: error score 1 - 2/3; 0.4 + 0.6 x 0.333 = 0.6.
        [online(latency_ms=50, error_count=2)] * 15,
        (1.0, 1.0, 1 / 3, 60),
        id="fast but error-prone",
    ),
    pytest.param(
        # 1 of 15 Offline; online at 300 ms with 7 errors over 14 online Health Reports.
        # 0.933 x (0.4 x 0.824 + 0.6 x 0.833) = 0.774.
        [offline()] + [online(latency_ms=300, error_count=n % 2) for n in range(14)],
        (14 / 15, 700 / 850, 1 - 0.5 / 3, 77),
        id="slightly degraded",
    ),
    pytest.param(
        # Nothing was measured while online, so latency and errors have no score.
        [offline()] * 15,
        (0.0, None, None, 0),
        id="offline all window",
    ),
]


@pytest.mark.parametrize(("reports", "expected"), SCENARIOS)
def test_scoring_scenarios(
    reports: list[WindowReport],
    expected: tuple[float, float | None, float | None, int],
) -> None:
    result = score_station(reports, DEFAULTS)

    availability, latency_score, error_score, hygiene_score = expected
    assert result.availability == pytest.approx(availability)
    assert result.latency_score == pytest.approx(latency_score)
    assert result.error_score == pytest.approx(error_score)
    assert result.hygiene_score == hygiene_score


def test_p95_latency_is_the_nearest_rank_95th_percentile() -> None:
    # 20 online Health Reports at 10, 20, ... 200 ms: the 19th smallest is the p95.
    reports = [online(latency_ms=10 * n) for n in range(20, 0, -1)]

    assert score_station(reports, DEFAULTS).p95_latency_ms == 190


def test_one_latency_spike_in_fifteen_sets_the_p95() -> None:
    # An average would hide the spike; the p95 does not.
    reports = [online(latency_ms=100)] * 14 + [online(latency_ms=1000)]

    result = score_station(reports, DEFAULTS)

    assert result.p95_latency_ms == 1000
    assert result.latency_score == 0.0


def test_errors_are_counted_per_online_health_report() -> None:
    # 12 errors over 4 online Health Reports is 3 per online report, whatever the offline count.
    reports = [online(error_count=3)] * 4 + [offline()] * 11

    assert score_station(reports, DEFAULTS).error_score == 0.0


def test_latency_on_offline_health_reports_is_ignored() -> None:
    # Offline Probes record a meaningless timeout latency.
    reports = [online(latency_ms=100)] * 10 + [offline(latency_ms=30_000)] * 5

    result = score_station(reports, DEFAULTS)

    assert result.p95_latency_ms == 100
    assert result.latency_score == 1.0
    assert result.hygiene_score == 67


@pytest.mark.parametrize(
    ("reports", "latency_score", "error_score"),
    [
        pytest.param([online(latency_ms=0)], 1.0, 1.0, id="latency below the good limit"),
        pytest.param([online(latency_ms=150)], 1.0, 1.0, id="latency at the good limit"),
        pytest.param([online(latency_ms=575)], 0.5, 1.0, id="latency halfway"),
        pytest.param([online(latency_ms=60_000)], 0.0, 1.0, id="latency beyond the bad limit"),
        pytest.param([online(error_count=9)], 1.0, 0.0, id="errors beyond the limit"),
    ],
)
def test_latency_and_error_scores_are_linear_and_clamped(
    reports: list[WindowReport], latency_score: float, error_score: float
) -> None:
    result = score_station(reports, DEFAULTS)

    assert result.latency_score == latency_score
    assert result.error_score == error_score


def test_limits_and_weights_are_configurable() -> None:
    config = ScoringConfig(
        latency_good_ms=100, latency_bad_ms=500, error_limit=2, latency_weight=0.5, error_weight=0.5
    )

    result = score_station([online(latency_ms=300, error_count=1)] * 10, config)

    assert result.latency_score == 0.5
    assert result.error_score == 0.5
    assert result.hygiene_score == 50


def test_the_hygiene_score_rounds_halves_up() -> None:
    # Availability 1/8 makes the Hygiene Score exactly 12.5.
    result = score_station([online()] + [offline()] * 7, DEFAULTS)

    assert result.hygiene_score == 13
