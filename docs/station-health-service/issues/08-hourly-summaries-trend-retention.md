# 08: Hourly summaries, trends, and retention

**What to build:** The worker builds hourly per-Station summaries for every completed hour that lacks one (so it self-heals after downtime), an operator can query hourly trends, and old raw Health Reports and summaries are removed automatically.

Spec: stories 48, 56–59; "Worker behaviour"; ADR-0001.

**Blocked by:** 03, 06

**Status:** ready-for-agent

- [x] For each completed hour within raw retention with no summary, the worker writes one row per (Station, hour): report count, online count, average/max/p95 latency, total errors, average Hygiene Score
- [x] Running catch-up twice produces no duplicate summaries
- [x] Trend endpoint (role `read`) returns hourly points for a requested number of past hours, optionally grouped by Region
- [x] Raw Health Reports older than 48h and summaries older than 30 days are deleted in bounded batches (configurable)
- [x] Integration tests: simulate a multi-hour worker outage and verify catch-up; verify trend output; verify retention boundaries
