# 13: Architecture & design document

**What to build:** The 2–4 page architecture & design document the brief calls "a key part of the evaluation", in Markdown, written from the decisions in the spec, `CONTEXT.md` and ADRs 0001–0003, and reconciled with what was actually built. It explains what was built and how it evolves to 100K+ Stations, using the glossary's vocabulary throughout.

Spec: `docs/station-health-service/spec.md` ("Architectural decisions recorded elsewhere", "Out of Scope", "Further Notes"); ADR-0001, ADR-0002, ADR-0003.

**Blocked by:** 05, 07, 09, 11

**Status:** ready-for-agent

- [ ] **High-level architecture:** Collector → API → MySQL ← worker; a diagram; why scoring is a periodic worker (ADR-0003)
- [ ] **Data model and schema:** each table with its role, keys and growth; the deliberate no-foreign-key / partition-ready Health Report table (ADR-0001)
- [ ] **API design:** endpoint summary, roles, idempotency, "latest" by timestamp, cursor paging, error shape; link to the generated OpenAPI spec
- [ ] **Scoring model:** formula, defaults, Flag/Clear Thresholds, minimum evidence to clear, Silent, Flag Reason, with the scenario table that motivated each choice; documented assumptions (60s Collector polling, Error Count meaning, Offline meaning)
- [ ] **Scaling (100K+ Stations):** volume/size figures per table; tiered storage (raw 48h → hourly 30d → daily 13 months → S3/Parquet) and daily partitions; worker cost and the move to incremental/streaming aggregation; p95 at scale (t-digest); batch ingest
- [ ] **Proactive alerting:** Flag Changes grouped by Region and Flag Reason per run, routed by Flag Reason (monitoring vs field service), via EventBridge; hysteresis prevents repeat alerts
- [ ] **Anomaly detection:** Station Anomaly as distinct from Poor Hygiene; same-hour-of-week baseline from hourly summaries plus peer comparison (Region, firmware); ML (RCF) as a later phase
- [ ] **Multi-region redundancy:** active-passive with Aurora Global Database and Route 53 failover now, regional cells later; Silent suppression and a single alert after a Monitoring Gap
- [ ] **Security:** what was built (role-scoped API keys, least privilege) and the production approach (API Gateway, IAM/mTLS for the Collector, Cognito/SSO for operators, Secrets Manager, TLS, rate limiting)
- [ ] **Testing strategy:** the two seams (HTTP API + "run worker once at `now`" against Testcontainers MySQL; pure scoring core), scenario-driven test cases, injected clock
- [ ] **CI/CD approach (described only):** lint, type check, tests, image build, OpenAPI check → ECR → staging → migrations as a pre-deploy step → smoke tests → approval → ECS rolling/blue-green with automatic rollback
- [ ] **AWS mapping:** ECS Fargate (API, worker), Aurora MySQL with read replica, API Gateway → SQS → ECS ingest consumers at scale (with the burst/failover rationale), EventBridge, CloudWatch (Logs Insights, Embedded Metric Format, alarms on scoring freshness, queue age, DLQ); Lambda as a rejected alternative
- [ ] **Observability:** structured logs, liveness/readiness, per-run worker log line
- [ ] **AI sections placeholder:** headed sections for "validating AI-generated code", "how AI tools influenced architectural decisions" and "trade-offs between AI assistance and manual coding" are present but left for the author to write — do not draft them
- [ ] Every statement about built behaviour matches the implementation (defaults, endpoints, tables); discrepancies are fixed in the doc or raised
- [ ] Fits in 2–4 pages; uses `CONTEXT.md` terms and avoids their listed synonyms
