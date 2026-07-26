"""keap-consolidate fan-out — the state ledger is where the real bug lives.

S2 (`docs/plans/cortex-corpus-parallel.md` §2.3/§2.4) turns the consolidator
into a sweep-once/feed-N job. Almost all of that is mechanical. ONE part is
not, and it is a silent data-loss bug if it is got wrong:

    the signature ledger is shared -> KEAP accepts an item -> the signature is
    recorded -> the organ, which was down, is NEVER OFFERED THAT ITEM AGAIN ->
    the two corpora differ forever, and the nightly diff reports it as an
    ingestion defect in the organ.

Nothing about that failure is visible at the moment it happens. So these cases
drive the real script against throwaway HTTP servers and assert the ledger, not
the log line. They never touch KEAP, the cortex organ, or the user tree.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "files" / "anatomy" / "scripts" / "keap-consolidate.py"


class _Sink(BaseHTTPRequestHandler):
    """A capture endpoint that can be told to fail, and records what it took."""

    def log_message(self, *_args):  # noqa: D401 - silence the default stderr spam
        pass

    def do_GET(self):  # noqa: N802
        if self.server.failing:
            self.send_error(503)
            return
        self._json(200, {"success": True, "data": {"status": "OK"}})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.server.failing:
            self.send_error(503)
            return
        self.server.received.append(body)
        self.server.tokens.add(self.headers.get("authorization", ""))
        self._json(201, {"success": True, "data": {"id": body.get("id"), "queued": True}})

    def _json(self, code: int, payload: dict):
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class Sink:
    def __init__(self):
        self.http = HTTPServer(("127.0.0.1", 0), _Sink)
        self.http.received = []
        self.http.tokens = set()
        self.http.failing = False
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.http.server_address[1]}"

    @property
    def received(self) -> list:
        return self.http.received

    @property
    def tokens(self) -> set:
        return self.http.tokens

    def fail(self, failing: bool = True) -> None:
        self.http.failing = failing

    def stop(self) -> None:
        self.http.shutdown()


@pytest.fixture()
def rig(tmp_path):
    keap, cortex = Sink(), Sink()
    root = tmp_path / "inbox"
    root.mkdir()
    (root / "a.md").write_text("alpha")
    (root / "b.md").write_text("beta")
    state = tmp_path / "state.json"

    def run(**overrides):
        env = {
            **os.environ,
            "HOME": str(tmp_path),
            "KEAP_API_URL": keap.url,
            "KEAP_AGENT_TOKEN_CAPTURE": "keap-secret",
            "CORTEX_API_URL": cortex.url,
            "CORTEX_AGENT_TOKEN_CAPTURE": "cortex-secret",
            "NOS_CONSOLIDATE_FS_ROOTS": str(root),
            "NOS_MARIADB_ROOT_PASSWORD": "",
            "NOS_NOTIFY_BIN": "",
        }
        env.update(overrides)
        proc = subprocess.run(
            [sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True, timeout=120
        )
        return proc

    # ~/.nos/keap-consolidate-state.json, under the fixture HOME.
    (tmp_path / ".nos").mkdir()
    yield run, keap, cortex, root, tmp_path / ".nos" / "keap-consolidate-state.json"
    keap.stop()
    cortex.stop()


def read_state(path: Path) -> dict:
    return json.loads(path.read_text())


def test_one_sweep_feeds_both_targets_and_each_gets_its_own_token(rig):
    run, keap, cortex, _root, state = rig
    proc = run()
    assert proc.returncode == 0, proc.stderr
    assert len(keap.received) == 2
    assert len(cortex.received) == 2
    # Capture ids are deterministic, so both stores key the same rows.
    assert {c["id"] for c in keap.received} == {c["id"] for c in cortex.received}
    # THE token check: each target sees ONLY its own secret. One env name meaning
    # two secrets on one host is how a write token reaches the wrong daemon.
    assert keap.tokens == {"Bearer keap-secret"}
    assert cortex.tokens == {"Bearer cortex-secret"}

    s = read_state(state)
    assert s["version"] == 2
    assert set(s["targets"]) == {"keap", "cortex"}
    assert len(s["targets"]["keap"]["fs"]) == 2
    assert len(s["targets"]["cortex"]["fs"]) == 2


def test_second_run_is_a_no_op_for_both(rig):
    run, keap, cortex, _root, _state = rig
    run()
    run()
    assert len(keap.received) == 2
    assert len(cortex.received) == 2


def test_a_down_target_does_not_record_state_and_does_not_fail_the_run(rig):
    """The bug this whole ledger redesign exists to prevent."""
    run, keap, cortex, _root, state = rig
    cortex.fail()
    proc = run()

    # The INCUMBENT decides the exit code. A shadow being down must never make
    # the production pipeline look broken.
    assert proc.returncode == 0, proc.stderr
    assert len(keap.received) == 2
    assert len(cortex.received) == 0

    s = read_state(state)
    assert len(s["targets"]["keap"]["fs"]) == 2
    # NOT recorded — this is the whole point. A shared ledger would have marked
    # these swept and the organ would never have seen them again.
    assert s["targets"].get("cortex", {}).get("fs", {}) == {}

    # …and the retry goes to the failed target ONLY.
    cortex.fail(False)
    proc = run()
    assert proc.returncode == 0, proc.stderr
    assert len(keap.received) == 2, "the incumbent must not be re-fed what it already took"
    assert len(cortex.received) == 2


def test_a_down_incumbent_is_fatal(rig):
    run, keap, cortex, _root, _state = rig
    keap.fail()
    proc = run()
    assert proc.returncode == 2
    assert len(cortex.received) == 0, "no target is fed when the incumbent is down"


def test_v1_state_is_read_as_the_incumbents_ledger(rig):
    """A v1 file describes ONE target's truth. Reading it as `targets.keap.*` is
    what stops the first run under the new job from re-sweeping every datapoint
    KEAP already holds."""
    run, keap, cortex, root, state = rig
    st = (root / "a.md").stat()
    state.write_text(
        json.dumps({"fs": {str(root / "a.md"): f"{int(st.st_mtime)}:{st.st_size}"}})
    )
    proc = run()
    assert proc.returncode == 0, proc.stderr

    # KEAP is not re-offered a.md; the organ, which has no ledger at all, gets both.
    assert [c["title"] for c in keap.received] == ["b.md"]
    assert sorted(c["title"] for c in cortex.received) == ["a.md", "b.md"]


def test_the_budget_counts_swept_items_not_posts(rig):
    """Otherwise a second target halves the effective sweep rate and a lagging
    target starves permanently behind a moving cap."""
    run, keap, cortex, _root, _state = rig
    proc = run(NOS_CONSOLIDATE_MAX="2")
    assert proc.returncode == 0, proc.stderr
    # Two items, two targets, four POSTs — under a budget of 2.
    assert len(keap.received) == 2
    assert len(cortex.received) == 2


def test_a_url_without_a_token_is_loud_rather_than_a_silent_single_target(rig):
    run, keap, cortex, _root, _state = rig
    proc = run(CORTEX_AGENT_TOKEN_CAPTURE="")
    assert proc.returncode == 0
    assert "is NOT being fed" in proc.stderr
    assert len(cortex.received) == 0
    assert len(keap.received) == 2
