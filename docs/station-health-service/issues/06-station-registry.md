# 06: Station Registry management

**What to build:** An admin can register, update, verify, delete and list Stations, and a seed command loads a realistic Station Registry with Regions. Registering a Station marks it verified; a registered Station that has never reported shows as Silent.

Spec: stories 26, 50–55; "API contracts → Station Registry".

**Blocked by:** 02, 04

**Status:** ready-for-agent

- [x] Register/update a Station by `station_id` with Region (role `admin`), idempotent, sets verified
- [x] Registering an Unverified Station confirms it
- [x] Delete a Station (role `admin`); its old Health Reports may remain and age out
- [x] List Stations (role `admin`), filterable to Unverified Stations
- [x] `read` and `ingest` keys get 403 on registry changes
- [x] Seed command loads N Stations across several Regions; documented in README
- [x] Integration test: a registered Station with no Health Reports is Silent and Poor Hygiene after a scoring run

## Comments

Implementation notes:

- `PUT /stations/{station_id}` with body `{"region": string | null}` (`region` is required, 1–64 characters, no other fields allowed). It returns `201` for a new Station and `200` otherwise, and always sets verified. A `station_id` longer than 64 characters gets `422`. Two concurrent first registrations of the same Station both return `201`.
- `DELETE /stations/{station_id}` returns `204`, or `404` if the Station is unknown. It also deletes the Station's `station_health` row, so a Station that comes back (re-registered, or auto-registered by a later Health Report) is assessed from `NOT_FLAGGED` rather than its stale flag state. Health Reports and Flag Changes are kept.
- Known race, left for 09 (worker safety): a scoring run that read the registry before a delete can upsert the deleted Station's health row again. The row is hidden (every read joins the registry), but a later re-registration would start from it.
- `GET /stations` is ordered by `station_id`, with a `verified` filter and cursor paging at the same 50/500 limits as the Poor Hygiene list. The spec didn't ask for paging; it is there because the registry can hold 100K Stations. Cursor encoding and page sizes now live in `station_health/paging.py`, shared by both lists.
- The seed command is `flask seed-stations --count N` (default 1000, `make seed N=...`). It registers `ST-000001`… as verified, assigning the Regions `us-west`, `us-east`, `eu-west`, `eu-central` and `ap-southeast` in turn, as one multi-row upsert per 1000 Stations. It is idempotent.
- The 05 tests now set Region and verified through this API instead of writing the `stations` table. Since registering always verifies, an Unverified Station never has a Region, and the 05 filter test was reshaped to match.
- Station responses are unchanged: `station_id`, `region`, `verified`.
