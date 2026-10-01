# 02: Ingest Health Reports with role-scoped API keys

**What to build:** The Collector can submit one Health Report per request with the six specified fields and get reliable, idempotent results. Health Reports for Stations not in the Station Registry are accepted and the Station is auto-registered as an Unverified Station with no Region. All endpoints are protected by API keys mapped to the `ingest`, `read` and `admin` roles; ingest requires `ingest`.

Spec: stories 1–10, 66; "API contracts → Ingest"; ADR-0001 (primary key, no foreign key).

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] A valid new Health Report returns 201 and is stored
- [ ] Resubmitting the same (`station_id`, `timestamp`) returns 200 and does not create a second record
- [ ] Malformed payloads (missing fields, wrong types, unknown connectivity status, negative latency or Error Count) return 422 with the consistent JSON error shape
- [ ] A timestamp more than 5 minutes in the future (configurable) returns 422
- [ ] A timestamp older than raw retention (48h, configurable) returns 422
- [ ] Late / out-of-order Health Reports are stored
- [ ] A Health Report for an unknown `station_id` auto-registers an Unverified Station with no Region
- [ ] Health Report storage has (`station_id`, `timestamp`) as primary key and no foreign key to Station
- [ ] No key → 401; key without the required role → 403; keys and their roles come from configuration
- [ ] The API-key security scheme appears in OpenAPI and works from Swagger UI
- [ ] Integration tests cover every criterion above through the HTTP API
