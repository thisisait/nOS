"""nOS E2E test suite (Anatomy A13 + A13.6).

Marks ``tests/e2e`` as a package so journey modules under ``journeys/`` can
do relative imports like ``from ..lib.tester_identity import ...``.
Without this file pytest still discovers the tests (rootdir is pinned by
pytest.ini) but ``importlib`` refuses to walk past the journey-package
boundary on relative-import resolution.
"""
