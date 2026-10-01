# 05: List Stations with Poor Hygiene

**What to build:** An operator can list all Stations with Poor Hygiene, worst first, filter it, and page through it consistently while scores change.

Spec: stories 40–44; "API contracts → List Stations with Poor Hygiene".

**Blocked by:** 04

**Status:** ready-for-agent

- [x] Endpoint (role `read`) returns only Stations with Poor Hygiene
- [x] Default order: Hygiene Score ascending with Silent treated as 0, ties by oldest "flagged since"
- [x] Optional sort by "flagged since"
- [x] Filters: Region, Flag Reason, verified
- [x] Cursor paging: default 50, maximum 500, opaque cursor; no Station is skipped or repeated across pages for a fixed dataset
- [x] Response includes total matching count and `scored_at`
- [x] Integration tests cover ordering, each filter, paging boundaries, and total count

## Comments

Implementation notes:

- The endpoint is `GET /poor-hygiene`, not under `/stations/`, so it can never shadow a Station whose ID is `poor-hygiene` on the registry's `/stations/<station_id>`.
- `sort` takes `score` (the default), `flagged_since` (oldest first) or `-flagged_since` (newest first). Story 41 asks for both longest-standing and newest. Under the `flagged_since` sorts, ties go to the worst score. Every sort ends with `station_id`, so its keys are unique.
- Paging is by keyset. The cursor is base64url JSON holding the sort, plus the last item's score (Silent as 0), "flagged since" and `station_id`. A cursor that is malformed, or that came from another sort, gets `400` with "The cursor is not valid.". `limit` outside 1–500 gets `422`.
- Filters are not stored in the cursor. A client that changes them mid-walk simply pages the new filter from that sort key onward.
- Items carry `station_id`, Region, verified, score (null while Silent), `silent`, `flag_reason` and `flagged_since`. The score parts stay on the station health endpoint.
- The list inner-joins the Station Registry, so a Station health row with no registry entry (for example once delete lands in 06) is not listed.
- Migration 0005 adds an index on `station_health (poor_hygiene, flagged_since)`.
- Until the registry API (06) exists, the filter tests set Region and verified by updating the `stations` row directly, as setup only. Switch them to the admin endpoint when it lands.
