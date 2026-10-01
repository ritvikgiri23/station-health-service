# 10: Simulator — live mode with scenario profiles

**What to build:** A reviewer can run a simulator that plays the Collector for N Stations, sending one Health Report per Station per simulated minute through the API, with Stations assigned to scenario profiles so every scoring rule is visibly exercised.

Spec: stories 67–69, 71; "Simulator".

**Blocked by:** 04, 06

**Status:** ready-for-agent

- [ ] Profiles: healthy, flapping, slow, error-prone, goes Silent, unregistered ID
- [ ] Speed multiplier compresses simulated time
- [ ] Sends via the HTTP API with an ingest key
- [ ] Runnable as an optional docker-compose profile; documented in README
- [ ] Smoke test: after a simulated window, each profile yields the expected outcome (Availability / latency / errors / silent Flag Reasons; unregistered → Unverified Station; healthy → not flagged)
