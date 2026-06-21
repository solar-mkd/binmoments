"""Synthetic sensor-data generator with ground-truth fault injection.

See ADR-008 (sensor data contract & synthetic simulator). The simulator emits realistic
streams AND injects known drift/anomalies/late-data/corrections so the analytical core
can be validated against ground truth.
"""
