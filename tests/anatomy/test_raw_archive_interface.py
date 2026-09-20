"""raw-archive-store unit (2026-09-20) — archive_put/archive_get, the shared
interface docs/plans/raw-archive-store.md named as the one piece of new code
its standard actually requires. Offline: scripted transport, no live RustFS.
"""
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
import raw_archive  # noqa: E402


def _store():
    """A tiny in-memory S3 double keyed on (method, path) — good enough to
    prove the PUT/GET round trip and the COMPLIANCE headers, without a live
    RustFS. Object Lock honesty itself is tools/raw-archive-probe.py's job."""
    objects: dict[str, bytes] = {}

    def transport(method, url, headers, body):
        from urllib.parse import urlparse
        path = urlparse(url).path
        if method == "PUT":
            if path == f"/{raw_archive.BUCKET}":
                return raw_archive.HttpResponse(200, {})
            assert "x-amz-object-lock-mode" in headers
            assert headers["x-amz-object-lock-mode"] == "COMPLIANCE"
            assert "x-amz-object-lock-retain-until-date" in headers
            objects[path] = body
            return raw_archive.HttpResponse(200, {})
        if method == "GET":
            if path in objects:
                return raw_archive.HttpResponse(200, {}, objects[path])
            return raw_archive.HttpResponse(404, {})
        raise AssertionError(f"unexpected method {method}")

    return transport, objects


def _enabled(monkeypatch=None):
    """Every live-transport test needs the explicit opt-in flag ON — this is
    the one file allowed to set it, and only against a SCRIPTED in-memory
    transport, never the real network."""
    os.environ["RAW_ARCHIVE_ENABLED"] = "1"


def test_disabled_by_default_returns_none_and_never_calls_transport():
    """THE retro-red case: this module's first version resolved creds
    whenever they were discoverable (e.g. via `docker inspect`) with no
    explicit opt-in — running the offline test suite on a host with a live
    RustFS reachable put real fixture objects into the operator's actual
    raw-archive bucket, COMPLIANCE-locked for 3650 days. Default must be OFF."""
    os.environ.pop("RAW_ARCHIVE_ENABLED", None)

    def transport(*a, **kw):
        raise AssertionError("transport must not be called unless RAW_ARCHIVE_ENABLED=1")

    assert raw_archive.archive_put("invoice", b"x", access="A", secret="B",
                                   transport=transport) is None
    assert raw_archive.archive_get("deadbeef", source="invoice", access="A", secret="B",
                                   transport=transport) is None


def test_put_then_get_round_trips_the_original_bytes():
    _enabled()
    try:
        transport, objects = _store()
        content = b"<isdoc>fixture bytes</isdoc>"
        h = raw_archive.archive_put("invoice", content, access="AKIAFAKE", secret="s3cr3t",
                                    transport=transport)
        assert h == raw_archive.content_hash(content)
        assert f"/{raw_archive.BUCKET}/raw/invoice/{h}" in objects

        got = raw_archive.archive_get(h, source="invoice", access="AKIAFAKE", secret="s3cr3t",
                                      transport=transport)
        assert got == content
    finally:
        os.environ.pop("RAW_ARCHIVE_ENABLED", None)


def test_key_convention_is_raw_source_content_hash():
    _enabled()
    try:
        transport, objects = _store()
        content = b"hello"
        h = raw_archive.archive_put("invoice", content, access="A", secret="B", transport=transport)
        assert list(objects) == [f"/{raw_archive.BUCKET}/raw/invoice/{h}"]
    finally:
        os.environ.pop("RAW_ARCHIVE_ENABLED", None)


def test_no_creds_is_a_graceful_none_never_a_raise(monkeypatch):
    """No AWS_* env AND no docker fallback (forced via monkeypatch — a real
    host, like this dev box, may have a live RustFS container reachable, and
    this test must not depend on that) — archive_put/get must return None,
    not raise (fail-open, never blocks the importer that calls it)."""
    _enabled()
    monkeypatch.setattr(raw_archive, "_creds_from_docker", lambda *a, **kw: None)
    env_backup = {k: os.environ.pop(k, None) for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")}
    try:
        assert raw_archive.archive_put("invoice", b"x", transport=lambda *a: (_ for _ in ()).throw(
            AssertionError("must not reach transport without creds"))) is None
    finally:
        os.environ.pop("RAW_ARCHIVE_ENABLED", None)
        for k, v in env_backup.items():
            if v is not None:
                os.environ[k] = v


def test_unreachable_endpoint_is_none_not_a_raise():
    _enabled()
    try:
        def transport(method, url, headers, body):
            raise OSError("connection refused")

        assert raw_archive.archive_put("invoice", b"x", access="A", secret="B",
                                       transport=transport) is None
        assert raw_archive.archive_get("deadbeef", source="invoice", access="A", secret="B",
                                       transport=transport) is None
    finally:
        os.environ.pop("RAW_ARCHIVE_ENABLED", None)
