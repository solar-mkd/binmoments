"""Ingestion and medallion layering (bronze raw landing, silver parse/normalize).

See ADR-009 (ingestion & medallion layering) and ADR-008 (the contract being ingested).
Bronze holds raw values + measurement identity; silver decomposes to channels and
resolves late data / corrections into signed deltas.
"""
