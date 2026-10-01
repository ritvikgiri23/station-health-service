# 03: Scoring run and station health status

**What to build:** A background worker computes each Station's Hygiene Score from its Health Reports in the Scoring Window, and an operator can retrieve a Station's latest health status: its latest Health Report plus its Hygiene Score breakdown and when it was scored. Introduces the pure scoring core (Availability, p95 latency, latency score, error score, weighted formula), the worker's "run once at `now`" entry point with an injected clock, a worker loop process in docker-compose, the Station health and scoring-run records.

Spec: stories 11–21, 31, 34–39; "Scoring formula"; "Worker behaviour"; ADR-0003.

**Blocked by:** 02

**Status:** ready-for-agent

- [x] Scoring core is pure (no Flask, no database) and takes window Health Reports, `now` and scoring configuration
- [x] Availability = share of Health Reports in the window that are not Offline
- [x] Latency score uses p95 of online Health Reports only, linear 150 ms → 1.0 to 1000 ms → 0.0 (configurable, clamped)
- [x] Error score uses errors per online Health Report, linear 0 → 1.0 to 3 → 0.0 (configurable, clamped)
- [x] Hygiene Score = Availability × (0.4 × latency score + 0.6 × error score) × 100, rounded; weights configurable; zero online Health Reports → 0
- [x] Table-driven unit tests cover the scoring scenarios in the spec (flapping, slow but reliable, fast but error-prone, slightly degraded, offline all window)
- [x] Worker "run once at `now`" scores every Station that has Health Reports in the window using one grouped read, and records the run (time, Stations scored, duration)
- [x] A worker process runs the loop every 60 seconds (configurable) in docker-compose
- [x] Station health endpoint (role `read`) returns `station_id`, Region, verified, latest Health Report by newest `timestamp`, the Hygiene Score with Availability/latency/error parts, and `scored_at` from the scoring-run record
- [x] A late-arriving older Health Report never replaces the latest Health Report in the response
- [x] Unknown Station returns 404
- [x] Integration tests: submit Health Reports via API → run worker once at a chosen `now` → assert via the health endpoint

## Comments

Implementation notes:

- The scoring core is `score_station(reports, config)`. It does not take `now` yet, because nothing in this slice uses it. Issue 04 adds `now` along with the previous flag state, for "flagged since".
- p95 uses nearest rank (always an observed latency). The Hygiene Score rounds halves up (12.5 → 13), unlike Python's `round`.
- Error Count is summed over online Health Reports only, then divided by the online count, consistent with ignoring Offline latency. Revisit if the Collector reports meaningful errors on Offline Probes.
- With no online Health Reports, latency score, error score and p95 are `null`, not 0.
- `LATENCY_WEIGHT` + `ERROR_WEIGHT` must add up to 1, so the score stays within 0–100.
- The health response's hygiene block also exposes `p95_latency_ms` and `report_count`.
- Interim gap until 04: a Station that stops reporting keeps its last `hygiene` block while `scored_at` advances. Silent handles this.
- With the default weights, a perfectly reliable Station at any latency scores at least 60 (0.6 × error score), which equals the default Flag Threshold. So latency alone never flags a Station. Worth keeping in mind for 04 and the simulator's "slow" profile.
