# 04: Poor Hygiene flagging, Silent, and Flag Changes

**What to build:** Stations enter and leave Poor Hygiene according to the Flag Threshold, Clear Threshold and minimum-evidence rule; Stations with no Health Reports in the Scoring Window become Silent and are Poor Hygiene; every flagged Station carries a Flag Reason and "flagged since"; every transition is recorded as a Flag Change. The scoring run writes only Stations whose visible state changed. All of this is visible in the station health response.

Spec: stories 22–30, 33, 36; "Scoring formula → Transitions"; ADR-0002, ADR-0003.

**Blocked by:** 03

**Status:** ready-for-agent

- [x] Not flagged → Poor Hygiene when score < Flag Threshold (default 60) or Silent
- [x] Poor Hygiene → cleared only when not Silent, score ≥ Clear Threshold (default 70), and ≥ 5 Health Reports in window (all configurable)
- [x] A Station with no Health Reports in the window is Silent with Flag Reason `silent`
- [x] Flag Reason for a scored Station is the lowest of Availability, latency score, error score, with deterministic tie-breaking
- [x] Each transition appends a Flag Change (Station, time, direction, Flag Reason, score); "flagged since" is set on entry and cleared on exit
- [x] Only Station health rows whose score, Silent, Poor Hygiene or Flag Reason changed are written in a run
- [x] Health endpoint exposes Silent, Poor Hygiene, Flag Reason and "flagged since"
- [x] Unit tests cover hysteresis (58/61/59/62 stays flagged), recovery after silence with one report (stays flagged), minimum-evidence clearing, and Flag Reason selection
- [x] Integration tests across successive `now` values verify entering Poor Hygiene, going Silent, and recovering, including Flag Change ordering

## Comments

Implementation notes:

- The scoring core's entry point is `assess_station(reports, previous_flag_state, now, config)`. It returns the score (`None` when Silent), the report count, the new flag state and the Flag Change, if any. `score_station` is unchanged.
- Flag Reasons are `silent`, `availability`, `latency` and `errors`. Ties go in that order. With no online Health Reports, Availability is 0, so the reason is `availability`.
- The Flag Reason is recomputed every run, so it can change while a Station stays flagged, with no Flag Change. One perfect Health Report after a silence (every part 1.0) therefore changes the reason from `silent` to `availability`. Keeping `silent` was tried and dropped: it showed `silent: false` alongside `flag_reason: silent`.
- Flag Reason and "flagged since" are null when a Station does not have Poor Hygiene. A Flag Change for leaving records the Flag Reason the Station last had while flagged.
- A Silent Station's score, Availability and the other parts are null, not 0. The poor-hygiene list (05) must sort it as 0.
- A run now assesses every Station in the Station Registry, so `stations_scored` counts registered Stations. Health Reports for a Station not in the registry are ignored.
- Only rows whose score, Silent, Poor Hygiene or Flag Reason changed are written. So Availability, latency and error scores, p95 latency and report count can lag while the integer score stays the same. This is documented in the response schema.
- `ScoringRun` also reports `stations_written` and `flag_changes`, and the worker logs both. The scoring-run record is unchanged.
- New settings: `FLAG_THRESHOLD`, `CLEAR_THRESHOLD` (each 0–100, with clear ≥ flag) and `MIN_REPORTS_TO_CLEAR` (≥ 1).
