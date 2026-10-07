"""No end-user-facing service renders the ansible-provisioned or a pulse.write token.

WHY (roadmap `face-holds-the-widest-token`, measured 2026-10-07). face's compose
handed the browser-facing container `wing_api_token` — the ansible-provisioned
row, `wing.write,pulse.write`, the Pulse catalog's writer — beside its own
`face-bff` token. A process a person below Tier 1 talks to must hold only a
token scoped to what that person may do.

End-user-facing = a manifest row with `rbac_tier >= 2` (a person below Tier 1
reaches it), plus openhuman (a desktop app an end user drives; no tier row).
The forbidden tokens are DERIVED from roles/pazny.wing/tasks/post.yml: the
ansible-provisioned mint and every mint whose literal scopes carry pulse.write.
Each is set to a sentinel and every template of those roles is RENDERED; a
sentinel in the output is red. A template that does not render is red too.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from test_docker_sock_only_behind_proxy import _env, _vars
from test_halt_has_a_break_glass import _run, needs_php, needs_vendor

REPO = Path(__file__).resolve().parents[2]
POST_YML = REPO / "roles/pazny.wing/tasks/post.yml"
MANIFEST = REPO / "state/manifest.yml"
#: End-user surfaces the manifest has no tier for, and why.
EXTRA = {"openhuman": "desktop app an end user drives; attaches through MCP"}


def forbidden_tokens() -> dict[str, str]:
    """{credential var: mint name} for ansible-provisioned and every pulse.write mint."""
    out = {}
    for m in re.finditer(r"--token=\{\{\s*(\w+)\s*\}\}\n\s*- --name=([\w-]+)\n(?:(?!--token=).*\n)*?.*--scopes=([^\n]+)",
                         POST_YML.read_text(encoding="utf-8")):
        var, name, scopes = m.groups()
        if name == "ansible-provisioned" or "pulse.write" in scopes.split(","):
            out[var] = name
    return out


def end_user_roles() -> dict[str, Path]:
    rows = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["services"]
    rows = rows.items() if isinstance(rows, dict) else ((r["id"], r) for r in rows)
    out = {}
    for sid, row in rows:
        if (row.get("rbac_tier") or 0) < 2 and sid not in EXTRA:
            continue
        for name in (sid, sid.replace("_", ""), sid.replace("_", "-"), row.get("fragment") or ""):
            if name and (REPO / f"roles/pazny.{name}/templates").is_dir():
                out[sid] = REPO / f"roles/pazny.{name}/templates"
                break
    return out


def leaks(text: str) -> list[str]:
    toks = forbidden_tokens()
    sentinel = {var: f"SENTINEL-{var}-0f3a" for var in toks}
    rendered = _env().from_string(text).render(**{**_vars("Darwin"), **sentinel})
    return sorted(f"{toks[v]} ({v})" for v, s in sentinel.items() if s in rendered)


def test_the_derivations_are_not_blind():
    toks = forbidden_tokens()
    assert toks.get("wing_api_token") == "ansible-provisioned", toks
    assert "face_bff_wing_api_token" not in toks, "face-bff is the token face SHOULD hold"
    roles = end_user_roles()
    assert {"face", "open_webui", "nextcloud", "openhuman"} <= set(roles), sorted(roles)


def test_the_detector_sees_the_measured_shape():
    assert leaks('NOS_WING_API_TOKEN: "{{ wing_api_token | default(\'\') }}"\n') == [
        "ansible-provisioned (wing_api_token)"]
    assert leaks('NOS_WING_BFF_TOKEN: "{{ face_bff_wing_api_token }}"\n') == []


def test_no_end_user_service_renders_an_estate_token():
    bad, blind = [], []
    for sid, tdir in sorted(end_user_roles().items()):
        for path in sorted(tdir.glob("*.j2")):
            try:
                bad += [f"{path.relative_to(REPO)}: {x}" for x in leaks(path.read_text(encoding="utf-8"))]
            except Exception as e:  # noqa: BLE001
                blind.append(f"{path.relative_to(REPO)}: {e!r}")
    assert not blind, "templates the gate cannot render (blind, not green):\n  " + "\n  ".join(blind)
    assert not bad, ("an end-user-facing service holds an estate token; give it a token scoped to "
                     "what its person may do (face: face-bff):\n  " + "\n  ".join(bad))


# ── Wing re-checks the tier on what face now asks with face-bff ─────────────

@needs_php
@needs_vendor
def test_wing_answers_face_bff_for_tier_one_only(tmp_path):
    user, admin = {"uid": "bob", "groups": "nos-users"}, {"uid": "alice", "groups": "nos-admins"}
    reads = [("Pulse", "jobs"), ("Pulse", "runs"), ("Pulse", "runSummary"), ("Events", "default"),
             ("Notifications", "default")]
    cases = [{"presenter": p, "action": a, "token": "bff", "method": "GET", **who}
             for p, a in reads for who in (user, admin)]
    cases += [{"presenter": "Pulse", "action": "runNow", "token": t, "params": {"id": "p:j"}, **who}
              for t, who in (("bff", user), ("bff", admin), ("agent", {}), ("ansible", {}))]
    cases += [{"presenter": "Pulse", "action": "jobs", "token": "bff", **admin}]  # POST = the catalog upsert
    got = [r["code"] if r["payload"] != "reached" else "reached" for r in _run(tmp_path, cases)]
    n = len(reads) * 2
    assert got[:n] == [403, "reached"] * len(reads), list(zip(cases, got))
    assert got[n:n + 4] == [403, "reached", 403, 403], got[n:n + 4]
    assert got[n + 4] == 403, "face-bff reached the Pulse catalog upsert"
