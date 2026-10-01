# 11: Simulator — history backfill

**What to build:** A reviewer can bulk-load the last 24 hours of Health Reports so trends show data immediately. Backfill goes through the service's own validation and storage logic (not HTTP) and relies on the worker's summary catch-up to build hourly summaries.

Spec: story 70; "Simulator"; ADR-0001.

**Blocked by:** 08, 10

**Status:** ready-for-agent

- [ ] Backfill command loads a configurable number of past hours (≤ raw retention) for the seeded Stations using batched inserts
- [ ] Every backfilled Health Report passes the same validation as ingest; duplicates are ignored
- [ ] After one worker run, the trend endpoint returns data for the backfilled hours
- [ ] Completes in under a minute for 500 Stations × 24h on a laptop; documented in README
