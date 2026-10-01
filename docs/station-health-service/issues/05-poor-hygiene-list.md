# 05: List Stations with Poor Hygiene

**What to build:** An operator can list all Stations with Poor Hygiene, worst first, filter it, and page through it consistently while scores change.

Spec: stories 40–44; "API contracts → List Stations with Poor Hygiene".

**Blocked by:** 04

**Status:** ready-for-agent

- [ ] Endpoint (role `read`) returns only Stations with Poor Hygiene
- [ ] Default order: Hygiene Score ascending with Silent treated as 0, ties by oldest "flagged since"
- [ ] Optional sort by "flagged since"
- [ ] Filters: Region, Flag Reason, verified
- [ ] Cursor paging: default 50, maximum 500, opaque cursor; no Station is skipped or repeated across pages for a fixed dataset
- [ ] Response includes total matching count and `scored_at`
- [ ] Integration tests cover ordering, each filter, paging boundaries, and total count
