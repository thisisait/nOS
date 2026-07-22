"""A probe must fail on a broken SERVICE, not on a missing DNS entry.

Linux has no `/etc/resolver` — that mechanism is macOS-only (tasks/dnsmasq.yml
says so in its own header), so `*.dev.local` never resolves there. The smoke
probes are URL-based, so on the Linux integration runner they reported a
**healthy estate as dead**: 7/8 DEAD with "Temporary failure in name
resolution" while the same run had just logged `iiab: 3/3 ready` and
`apps: 5/5 ready` (CI 2026-07-22).

This is the gates.md failure in its mirror image — not a green check that
measured nothing, but a RED one measuring a layer the platform never provides.
It stayed hidden while few services were enabled: the systemic-failure ratio
(default 0.5) absorbed one or two dead probes, and only tipped over when the
probe count grew. A tolerance that hides a structural mismatch until it scales
is a hidden fee.

The fallback re-sends the request to the loopback edge with the original Host
header, which tests what we actually care about — does the reverse proxy route
this service — and is labelled so a run that never exercised DNS cannot be
mistaken for one that did.
"""

from __future__ import annotations

import importlib.util
import pathlib
import ssl
import urllib.error

REPO = pathlib.Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("nos_smoke", REPO / "tools" / "nos-smoke.py")
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


def test_name_resolution_errors_are_recognised():
    for reason in (
        "Temporary failure in name resolution",
        "[Errno 8] nodename nor servname provided, or not known",
        "Name or service not known",
    ):
        exc = urllib.error.URLError(reason)
        assert smoke._is_name_resolution_error(exc), reason


def test_other_errors_are_not_mistaken_for_dns():
    """Connection refused means the service IS down — it must stay a failure."""
    exc = urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))
    assert not smoke._is_name_resolution_error(exc)


def test_fallback_only_applies_to_local_tlds():
    """Never re-point a public hostname at our own loopback — that would turn
    'the internet is unreachable' into 'our edge answered', a false green."""
    assert smoke._loopback_ok("https://wing.dev.local/")
    assert smoke._loopback_ok("https://x.example.test/")
    assert not smoke._loopback_ok("https://wing.pazny.eu/")
    assert not smoke._loopback_ok("https://github.com/")
