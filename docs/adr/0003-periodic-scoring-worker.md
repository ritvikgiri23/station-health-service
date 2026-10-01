# Hygiene Scores are computed by a periodic worker, not at ingest

Silent Stations are defined by the absence of Health Reports, so anything triggered by report arrival can never detect them; computing scores on every read would mean aggregating ~1.5M raw rows per poor-hygiene query at 100K Stations. We therefore keep ingest as a plain insert and run a separate worker process (same codebase and image) every 60 seconds that scores every registered Station from its Scoring Window in one grouped read, writes only Stations whose visible state changed, appends Flag Changes, and records the run's completion time for freshness.

## Consequences

- Scores can be up to ~60 seconds old; every score response carries `scored_at` from the scoring-run record, and readiness reports degraded when it is older than ~3 minutes.
- Station health rows are not touched when unchanged, so their own timestamps say nothing about freshness — only the scoring-run record does.
- A MySQL named lock ensures only one scoring run executes at a time; concurrent workers skip rather than queue.
- The same worker builds hourly summaries for any missing completed hour, so it catches up by itself after downtime.
- The worker exposes a "run once at `now`" entry point with an injected clock, which is the main test seam.

## Considered Options

- Recompute on each Health Report: never detects Silent, and costs ~1,700 window recomputations per second.
- Compute at read time: correct but too expensive for list and metrics queries at scale.
- Recompute on ingest plus a read-time staleness check: detects Silent but never records when a Station became Silent, so alerting has nothing to hook into.
