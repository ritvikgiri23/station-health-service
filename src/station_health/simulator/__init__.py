"""The simulator: plays the Collector for a fleet of Stations with scenario profiles.

Live mode (`python -m station_health.simulator`) sends Health Reports over HTTP; backfill
(`flask backfill-reports`) loads past hours directly through ingest's validation and storage.
"""
