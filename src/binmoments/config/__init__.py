"""Per-instrument configuration loading.

See ADR-011 (configuration & secrets). Behaviour is declarative config; type-level
defaults with per-instrument overrides; secrets are referenced from the platform secret
store, never embedded.
"""
