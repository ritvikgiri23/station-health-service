# Tiered storage for Health Reports

At 100K Stations probed every 60s we receive ~144M Health Reports a day (~10 TB/year raw), which a single MySQL table cannot hold sensibly — yet scoring only ever needs the last Scoring Window of raw data. We therefore store reports in tiers: raw Health Reports for 48 hours, hourly per-Station summaries for 30 days, daily summaries for 13 months, and an S3/Parquet archive beyond that. Only the raw and hourly tiers are built; daily summaries, the archive, and daily range partitions on the raw table are described in the design doc.

## Consequences

- The raw Health Report table deliberately has **no foreign key to Station** and uses (`station_id`, `timestamp`) as its primary key, because MySQL partitioned tables forbid foreign keys and require the partition column in every unique key. Don't "fix" this by adding a foreign key.
- Reports older than raw retention are rejected at ingest, and history older than 48 hours is only available as summaries.
- The 30-day hourly tier is sized to give the four-week same-hour-of-week baseline anomaly detection needs.

## Considered Options

- Partitioning + retention only (no summaries): loses trends beyond the retention period.
- Storing only state changes: breaks Availability and makes Silent ambiguous.
- A time-series database for raw data: conflicts with the brief's relational requirement and adds a system to operate.
