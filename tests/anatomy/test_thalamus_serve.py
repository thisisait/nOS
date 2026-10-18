"""`thalamus serve` acts only as the person the receptor's identity map names.

WHY. The thalamus holds KEAP's proxy secret, so whatever it sends KEAP is believed.
A peer the map does not name must be refused (never defaulted to akadmin), KEAP
must see the mapped person, and the secret must reach no log, ledger or model.
CI runs pytest, not cargo, so this file runs `cargo test --test serve`.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
CRATE = REPO / "files/anatomy/thalamus/thalamus"


def test_one_identity_map_one_renderer():
    """Ruling 1: the thalamus reads the receptor's map; it renders none of its own."""
    src = (CRATE / "src/serve.rs").read_text()
    assert ".nos/identity-map.yml" in src
    assert not list(CRATE.rglob("*identity-map*")), "a second map drifts from the receptor's"


def test_the_relay_door_is_gated_in_the_serve_lane():
    """Row thalamus-web-relay: the face's door is pinned by name in the lane test_the_daemon_runs runs."""
    src = (CRATE / "tests/serve.rs").read_text()
    for name in ("the_relay_refuses_no_hello_or_a_wrong_secret", "the_relay_refuses_a_person_it_cannot_name_by_name",
                 "a_relay_person_acts_only_as_themselves_and_the_secret_goes_nowhere",
                 "a_relay_decision_is_the_persons_and_an_unlisted_socket_peer_still_is_not",
                 "a_second_tab_takes_the_persons_session_over", "an_empty_relay_secret_binds_no_door"):
        assert f"fn {name}()" in src, name


@pytest.mark.skipif(not shutil.which("cargo"), reason="cargo runs the daemon")
def test_the_daemon_runs():
    r = subprocess.run(["cargo", "test", "--quiet", "--manifest-path", str(CRATE / "Cargo.toml"),
                        "--test", "serve"], capture_output=True, text=True, timeout=600, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    n = re.search(r"(\d+) passed", r.stdout)
    assert n and int(n[1]) >= 3, r.stdout
