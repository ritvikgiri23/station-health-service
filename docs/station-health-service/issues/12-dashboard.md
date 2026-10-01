# 12: Dashboard page

**What to build:** An operator can open a single page served by the service that shows fleet summary tiles, the Poor Hygiene list with Flag Reasons, and a 24-hour trend chart, working locally with a read-only demo key. First item to drop if time runs short.

Spec: stories 72–73.

**Blocked by:** 05, 07, 08

**Status:** ready-for-agent

- [x] Page is static HTML/JS served by the API, no build step
- [x] Summary tiles from the metrics snapshot
- [x] Poor Hygiene table (worst first) with Flag Reason and "flagged since"
- [x] 24-hour trend chart from the trend endpoint
- [x] Uses a read-only demo key injected for local use only; documented in README
- [x] Integration test: page is served and references only `read`-role endpoints
