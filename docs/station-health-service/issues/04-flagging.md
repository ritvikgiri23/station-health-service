# 04: Poor Hygiene flagging, Silent, and Flag Changes

**What to build:** Stations enter and leave Poor Hygiene according to the Flag Threshold, Clear Threshold and minimum-evidence rule; Stations with no Health Reports in the Scoring Window become Silent and are Poor Hygiene; every flagged Station carries a Flag Reason and "flagged since"; every transition is recorded as a Flag Change. The scoring run writes only Stations whose visible state changed. All of this is visible in the station health response.

Spec: stories 22–30, 33, 36; "Scoring formula → Transitions"; ADR-0002, ADR-0003.

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] Not flagged → Poor Hygiene when score < Flag Threshold (default 60) or Silent
- [ ] Poor Hygiene → cleared only when not Silent, score ≥ Clear Threshold (default 70), and ≥ 5 Health Reports in window (all configurable)
- [ ] A Station with no Health Reports in the window is Silent with Flag Reason `silent`
- [ ] Flag Reason for a scored Station is the lowest of Availability, latency score, error score, with deterministic tie-breaking
- [ ] Each transition appends a Flag Change (Station, time, direction, Flag Reason, score); "flagged since" is set on entry and cleared on exit
- [ ] Only Station health rows whose score, Silent, Poor Hygiene or Flag Reason changed are written in a run
- [ ] Health endpoint exposes Silent, Poor Hygiene, Flag Reason and "flagged since"
- [ ] Unit tests cover hysteresis (58/61/59/62 stays flagged), recovery after silence with one report (stays flagged), minimum-evidence clearing, and Flag Reason selection
- [ ] Integration tests across successive `now` values verify entering Poor Hygiene, going Silent, and recovering, including Flag Change ordering
