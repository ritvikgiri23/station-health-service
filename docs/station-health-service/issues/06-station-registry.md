# 06: Station Registry management

**What to build:** An admin can register, update, verify, delete and list Stations, and a seed command loads a realistic Station Registry with Regions. Registering a Station marks it verified; a registered Station that has never reported shows as Silent.

Spec: stories 26, 50–55; "API contracts → Station Registry".

**Blocked by:** 02, 04

**Status:** ready-for-agent

- [ ] Register/update a Station by `station_id` with Region (role `admin`), idempotent, sets verified
- [ ] Registering an Unverified Station confirms it
- [ ] Delete a Station (role `admin`); its old Health Reports may remain and age out
- [ ] List Stations (role `admin`), filterable to Unverified Stations
- [ ] `read` and `ingest` keys get 403 on registry changes
- [ ] Seed command loads N Stations across several Regions; documented in README
- [ ] Integration test: a registered Station with no Health Reports is Silent and Poor Hygiene after a scoring run
