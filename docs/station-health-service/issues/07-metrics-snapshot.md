# 07: Aggregated metrics snapshot

**What to build:** An operator can see current fleet health overall, per Region, or per firmware version.

Spec: stories 45–47, 49; "API contracts → Metrics snapshot".

**Blocked by:** 04, 06

**Status:** ready-for-agent

- [x] Endpoint (role `read`) returns station count, Poor Hygiene count and percentage, Silent count, Unverified Station count, average Hygiene Score, average Availability, average p95 latency
- [x] Optional grouping by Region (Stations without Region grouped as `unassigned`) or by firmware version
- [x] Served from Station health / Station Registry, not raw Health Reports
- [x] Integration tests verify figures for a known dataset, overall and for each grouping
