# 09: Worker concurrency safety and score freshness

**What to build:** Only one scoring run executes at a time even with multiple workers, a stuck or dead worker is visible through readiness, and each run leaves a single summary log line.

Spec: stories 32, 61, 63; ADR-0003.

**Blocked by:** 03

**Status:** ready-for-agent

- [x] A scoring run takes a MySQL named lock and skips (does not wait) if it is held
- [x] Two concurrent runs at the same `now` produce no duplicate Flag Changes
- [x] Readiness reports degraded when the last scoring run is older than ~3 minutes (configurable)
- [x] Each run logs one structured line: Stations scored, Flag Changes, Silent count, duration
- [x] Integration tests cover lock contention and stale-score readiness
