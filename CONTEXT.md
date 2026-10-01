# Station Health

Ingests health telemetry from EV charging stations and judges each station's network hygiene so that problematic stations can be found.

## Language

**Station**:
An EV charging station monitored by the Collector, identified by its `station_id`.
_Avoid_: Charger, device, unit

**Station Registry**:
The list of Stations that are expected to exist, with fixed facts about each (such as Region). A registered Station that never reports is Silent.
_Avoid_: Inventory, catalogue, asset list

**Unverified Station**:
A Station added to the Station Registry automatically because a Health Report arrived for it before anyone registered it; it is scored normally until an operator confirms or removes it.
_Avoid_: Unknown station, ghost, auto-station

**Region**:
The geographic grouping a Station belongs to, held in the Station Registry rather than in Health Reports.
_Avoid_: Zone, area, market

**Collector**:
The NOC monitoring component that probes each station on a schedule and writes a Health Report for every probe, whether or not the station answered.
_Avoid_: Poller, prober, agent

**Probe**:
One check of one station by the Collector. Every Probe produces exactly one Health Report.
_Avoid_: Poll, ping, check

**Health Report**:
The result of one Collector probe of a station at one point in time (connectivity, latency, errors, firmware).
_Avoid_: Heartbeat, ping, event, telemetry record

**Offline**:
The connectivity status recorded when a station did not answer the Collector's probe; a fault with the station, not with monitoring.
_Avoid_: Down, disconnected

**Error Count**:
The number of errors a station experienced since its previous Health Report (not a running total).
_Avoid_: Total errors, error counter

**Hygiene Score**:
A judgement of a station's network health computed from its recent Health Reports, not from any single report. It is the station's Availability scaled by how well it performed while online, so an often-offline station can never score well.
_Avoid_: Health score, report score

**Availability**:
The share of a station's Health Reports in the Scoring Window that are not Offline.
_Avoid_: Uptime, connectivity score

**Scoring Window**:
The span of time leading up to now whose Health Reports a station's Hygiene Score is computed from.
_Avoid_: Lookback, recent reports, last N

**Silent**:
A registered station with no Health Reports in its Scoring Window, meaning no probe result reached us — usually a gap in monitoring rather than a station fault. A Silent station always has Poor Hygiene.
_Avoid_: Stale, unknown, missing, dead

**Monitoring Gap**:
A period when Health Reports failed to reach us because of our own systems (Collector, intake or failover), during which Silent stations are not blamed individually.
_Avoid_: Outage, blackout, data gap

**Poor Hygiene**:
The condition of a station that is either Silent or has fallen below the Flag Threshold and not yet recovered to the Clear Threshold; such a station is flagged as problematic.
_Avoid_: Unhealthy, bad, failing

**Flag Threshold**:
The Hygiene Score below which a station enters Poor Hygiene.

**Clear Threshold**:
The higher Hygiene Score a flagged station must reach, backed by a minimum number of Health Reports in its Scoring Window, to leave Poor Hygiene. Flagging is quick; clearing must be earned.
_Avoid_: Recovery threshold, reset threshold

**Flag Reason**:
Why a station has Poor Hygiene: Silent, or whichever of Availability, latency or errors scored worst.
_Avoid_: Cause, root cause, failure type

**Station Anomaly**:
Behaviour that is unusual for a station relative to its own history or its peers, even if its Hygiene Score is acceptable. Separate from Poor Hygiene, which is judged against fixed thresholds.
_Avoid_: Outlier, alert, deviation

**Flag Change**:
The moment a station enters or leaves Poor Hygiene, recorded with when and why.
_Avoid_: Alert, incident, transition, status change
