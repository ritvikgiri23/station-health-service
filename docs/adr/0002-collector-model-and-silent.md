# Health Reports come from a Collector; Silent means Poor Hygiene

The brief's payload includes `connectivity_status: offline`, which only makes sense if something other than the Station writes the report. We model Health Reports as the output of a NOC Collector that Probes each Station on a schedule and writes a report for every Probe, so Offline means "the Probe failed" and `latency_ms` is the Probe's round-trip time. It follows that a registered Station with no Health Reports in its Scoring Window — Silent — usually indicates a gap in our own monitoring, not a Station fault; we still treat Silent as Poor Hygiene (Flag Reason `silent`), because an unchecked Station must never be presented to drivers as working.

## Consequences

- Silent detection needs the Station Registry (to know which Stations should exist) and a periodic scoring run (no report arrives to trigger it) — see ADR-0003.
- Because our own outages make Stations Silent, a Monitoring Gap (Collector, intake or failover failure) can flag the whole fleet at once; the design doc's alerting groups Flag Changes by Region and Flag Reason, and multi-region failover suppresses Silent Flag Changes for one Scoring Window after a Monitoring Gap.
- Error Count is assumed to be errors since the previous Health Report, not a running total; the brief's six fields carry no boot identifier to make a running total reliable.

## Considered Options

- Stations push their own heartbeats: leaves `offline` reports unexplained except as buffered uploads.
- Treat Silent as "unknown" rather than Poor Hygiene: drivers read "unknown" as "don't go", and it hides real outages from the problem list.
