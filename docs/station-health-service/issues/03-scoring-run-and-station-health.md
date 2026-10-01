# 03: Scoring run and station health status

**What to build:** A background worker computes each Station's Hygiene Score from its Health Reports in the Scoring Window, and an operator can retrieve a Station's latest health status: its latest Health Report plus its Hygiene Score breakdown and when it was scored. Introduces the pure scoring core (Availability, p95 latency, latency score, error score, weighted formula), the worker's "run once at `now`" entry point with an injected clock, a worker loop process in docker-compose, the Station health and scoring-run records.

Spec: stories 11–21, 31, 34–39; "Scoring formula"; "Worker behaviour"; ADR-0003.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] Scoring core is pure (no Flask, no database) and takes window Health Reports, `now` and scoring configuration
- [ ] Availability = share of Health Reports in the window that are not Offline
- [ ] Latency score uses p95 of online Health Reports only, linear 150 ms → 1.0 to 1000 ms → 0.0 (configurable, clamped)
- [ ] Error score uses errors per online Health Report, linear 0 → 1.0 to 3 → 0.0 (configurable, clamped)
- [ ] Hygiene Score = Availability × (0.4 × latency score + 0.6 × error score) × 100, rounded; weights configurable; zero online Health Reports → 0
- [ ] Table-driven unit tests cover the scoring scenarios in the spec (flapping, slow but reliable, fast but error-prone, slightly degraded, offline all window)
- [ ] Worker "run once at `now`" scores every Station that has Health Reports in the window using one grouped read, and records the run (time, Stations scored, duration)
- [ ] A worker process runs the loop every 60 seconds (configurable) in docker-compose
- [ ] Station health endpoint (role `read`) returns `station_id`, Region, verified, latest Health Report by newest `timestamp`, the Hygiene Score with Availability/latency/error parts, and `scored_at` from the scoring-run record
- [ ] A late-arriving older Health Report never replaces the latest Health Report in the response
- [ ] Unknown Station returns 404
- [ ] Integration tests: submit Health Reports via API → run worker once at a chosen `now` → assert via the health endpoint
