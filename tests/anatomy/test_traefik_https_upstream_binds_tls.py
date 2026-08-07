"""Anatomy gate — an upstream is HTTP until an internal TLS listener is measured.

Subject: `traefik_https_upstream_ids` in roles/pazny.traefik/vars/main.yml.
Doctrine: docs/doctrine/foreign-properties.md §3 (the upstream fact) and §3.1
(the rule this gate performs).

WHAT THIS GATE IS FOR, said plainly: the list is `[]` today and **empty is the
current correct answer**, not a gap — every routed upstream in this estate
terminates TLS at the edge and speaks plain HTTP behind it. So this gate does
NOT assert a population; a gate that asserted membership of an empty set would
be asserting on silence (docs/doctrine/gates.md). It exists to refuse a
CARELESS ADDITION, and the refusal is what carries substance while the set is
empty: `refuse()` is a pure function, exercised here against the exact addition
that was once live and once broke the edge.

The addition it refuses is not hypothetical. `code_server` sat in this list
until 2026-05-04: the LSIO image serves plain HTTP on container port 8443
unless `--cert` is passed, which nOS does not pass, so Traefik opened a TLS
handshake the upstream answered in HTTP — `tls_get_more_records: packet length
too long`, a user-visible 502/404 on code.pazny.eu. The port number said TLS
and nothing measured the listener.

Offline, no Docker: reads two committed files.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
TRAEFIK_VARS = REPO / "roles" / "pazny.traefik" / "vars" / "main.yml"
MANIFEST = REPO / "state" / "manifest.yml"
CODE_SERVER_COMPOSE = REPO / "roles" / "pazny.code_server" / "templates" / "compose.yml.j2"

#: id → `path:line` citing the container's OWN TLS listener. EMPTY, and that is
#: the measured answer for this estate, not an unfinished list. Whoever adds an
#: id adds its evidence here; the evidence is re-read on every run, so a
#: citation that stops being true fails rather than ages quietly.
#:
#: What counts: the line that makes the listener TLS — a `--cert`/`--key` flag,
#: an `ssl_certificate`/`certfile` setting, an `https://` bind. What does not
#: count, ever: the port number (docs/doctrine/foreign-properties.md §3.1).
TLS_EVIDENCE: dict[str, str] = {}

#: Substrings that make a cited line evidence of TLS rather than a mention of it.
TLS_MARKERS = ("--cert", "--key", "ssl_cert", "ssl_certificate", "certfile",
               "cert_file", "tls", "https://")


def refuse(ids, evidence: dict[str, str], known_ids: set[str],
           root: Path = REPO) -> list[str]:
    """Reasons each id may NOT be declared an HTTPS upstream. Empty list = fine.

    Pure: everything it needs is passed in, so the refusal can be exercised
    against an addition nobody has made.
    """
    reasons: list[str] = []
    for sid in ids:
        if sid not in known_ids:
            reasons.append(
                f"{sid!r}: names no service in state/manifest.yml — a typo here "
                f"is silent, the router simply keeps its http:// upstream")
            continue
        cite = evidence.get(sid)
        if not cite:
            reasons.append(
                f"{sid!r}: no measured evidence of an internal TLS listener. "
                f"Add `path:line` to TLS_EVIDENCE naming the line that makes "
                f"the listener TLS. A port number is not evidence "
                f"(docs/doctrine/foreign-properties.md §3.1)")
            continue
        path, _, lineno = cite.partition(":")
        target = root / path
        if not target.exists():
            reasons.append(f"{sid!r}: evidence cites {path}, which does not exist")
            continue
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        if not lineno.isdigit() or not (1 <= int(lineno) <= len(lines)):
            reasons.append(
                f"{sid!r}: evidence {cite} does not point at a line of {path} "
                f"({len(lines)} lines) — re-measure, do not renumber by guess")
            continue
        line = lines[int(lineno) - 1].lower()
        if not any(marker in line for marker in TLS_MARKERS):
            reasons.append(
                f"{sid!r}: evidence {cite} no longer says anything about TLS: "
                f"{lines[int(lineno) - 1].strip()!r}")
    return reasons


@pytest.fixture(scope="module")
def declared() -> list:
    data = yaml.safe_load(TRAEFIK_VARS.read_text(encoding="utf-8"))
    assert "traefik_https_upstream_ids" in data, (
        "traefik_https_upstream_ids is gone from roles/pazny.traefik/vars/main.yml. "
        "services.yml.j2 reads it through `| default([])`, so deleting it does not "
        "break a render — it deletes the decision, and with it the only place the "
        "HTTP-until-measured rule is written down "
        "(docs/doctrine/foreign-properties.md §3.1)")
    ids = data["traefik_https_upstream_ids"]
    assert isinstance(ids, list), (
        f"traefik_https_upstream_ids must be a list, got {type(ids).__name__}")
    return ids


@pytest.fixture(scope="module")
def manifest_ids() -> set[str]:
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    ids = {s["id"] for s in data["services"]}
    assert len(ids) > 40, "manifest harvest collapsed — refuse() would pass on nothing"
    return ids


def test_every_declared_https_upstream_carries_measured_evidence(declared, manifest_ids):
    """The live check. Vacuous today BY MEASUREMENT — the list is empty — and
    the tests below are what keep the refusal honest in the meantime."""
    reasons = refuse(declared, TLS_EVIDENCE, manifest_ids)
    assert not reasons, (
        "an id in traefik_https_upstream_ids is not shown to bind TLS internally:\n  "
        + "\n  ".join(reasons))


def test_an_unevidenced_addition_is_refused(manifest_ids):
    """The addition that actually happened, refused: code_server, no evidence."""
    reasons = refuse(["code_server"], {}, manifest_ids)
    assert len(reasons) == 1 and "no measured evidence" in reasons[0]
    assert "§3.1" in reasons[0], "the refusal must send the reader to the doctrine"


def test_an_id_no_service_answers_to_is_refused(manifest_ids):
    reasons = refuse(["cod_server"], {"cod_server": "x:1"}, manifest_ids)
    assert len(reasons) == 1 and "manifest" in reasons[0]


def test_evidence_that_stopped_being_true_is_refused(manifest_ids, tmp_path):
    """A citation is re-read, not remembered. Three ways it can rot, all red."""
    (tmp_path / "compose.j2").write_text(
        "services:\n  x:\n    command: serve --http 0.0.0.0:8443\n", encoding="utf-8")
    ev_gone = {"code_server": "roles/pazny.nonexistent/compose.j2:3"}
    ev_offend = {"code_server": "compose.j2:3"}
    ev_range = {"code_server": "compose.j2:99"}
    assert "does not exist" in refuse(["code_server"], ev_gone, manifest_ids)[0]
    assert "no longer says anything about TLS" in refuse(
        ["code_server"], ev_offend, manifest_ids, root=tmp_path)[0]
    assert "does not point at a line" in refuse(
        ["code_server"], ev_range, manifest_ids, root=tmp_path)[0]


def test_valid_evidence_passes(manifest_ids, tmp_path):
    """The gate must be passable, or it is a ban wearing a gate's clothes."""
    (tmp_path / "compose.j2").write_text(
        "services:\n  x:\n    command: serve --cert /certs/tls.crt\n", encoding="utf-8")
    assert refuse(["code_server"], {"code_server": "compose.j2:3"},
                  manifest_ids, root=tmp_path) == []


def test_code_server_is_absent_and_the_reason_still_holds(declared):
    """The known instance, re-measured rather than remembered: our own
    healthcheck probes http:// on 8443, and nothing passes --cert. If either
    changes upstream, this fails and asks for a re-measurement — which is the
    only thing that could ever justify the entry."""
    assert "code_server" not in declared, (
        "code_server is in traefik_https_upstream_ids. The LSIO image serves "
        "PLAIN HTTP on 8443 unless --cert is passed; this entry cost a 502/404 "
        "on code.pazny.eu once already "
        "(docs/doctrine/foreign-properties.md §3)")
    compose = CODE_SERVER_COMPOSE.read_text(encoding="utf-8")
    assert "http://localhost:8443" in compose, (
        "the code-server healthcheck no longer probes http:// on 8443 — the "
        "upstream's scheme changed, so re-measure §3 before trusting either "
        "this gate or the doctrine paragraph")
    # Comment lines are where the rule is EXPLAINED (they say "--cert"
    # themselves); only a rendered line can actually pass the flag.
    rendered = [ln for ln in compose.splitlines() if not ln.lstrip().startswith("#")]
    assert not any("--cert" in ln for ln in rendered), (
        "compose now passes --cert to code-server: the image WOULD then bind "
        "TLS on 8443 and §3 needs rewriting, together with this gate's premise")
