"""Smoke test: the package imports and the test runner is wired correctly.

Run with `pytest` from the repo root. This is a placeholder so the test harness is
green from the first commit; real tests arrive with the vertical slice.
"""

import binmoments


def test_package_imports():
    assert binmoments.__version__ == "0.1.0"
