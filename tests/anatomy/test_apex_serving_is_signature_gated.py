"""Anatomy CI gate — the apex page cannot be served while its ruling is unsigned.

files/anatomy/apex/ruling.yml is the operator-signable allow-list deciding
what may appear on an unauthenticated page at the ROOT domain. While it says
``status: PROPOSED`` the page is a local preview and nothing else. The serving
path built around it (roles/pazny.apex + the manifest route + the Traefik
auth-mode) must therefore REFUSE — loudly, at converge — until a person signs.

What is pinned, and why it cannot be satisfied by editing itself:

  1. ``projection.serve_gate`` refuses PROPOSED and refuses SIGNED-with-nobody,
     and passes SIGNED-with-a-name — mutation-verified in BOTH directions on
     copies, never by flipping the committed status.
  2. The converge command itself (the exact ``build.py --require-signed --out``
     shape the role runs) exits 4 and writes NOTHING on an unsigned ruling,
     and exits 0 and writes the site on a signed one — proven end-to-end in a
     throwaway repo mirror, so a refactor of build.py's flag parsing cannot
     silently drop the gate while this stays green.
  3. The role's task file gates BEFORE it renders: the assert precedes the
     build, the build precedes the compose-override template, and the build
     argv carries --require-signed. Belt and braces by construction — either
     layer alone still refuses.
  4. build.py accepts no ruling-path override: the gate reads the committed
     ruling or nothing. A flag pointing the gate at a permissive copy would
     be the gate editing itself.
  5. The prepared-but-inert route facts: manifest entry (domain_var+port_var,
     so the exposure gate's population sees it), auth mode 'none' WITH the
     REM-144 justification field, the container upstream, the read-only
     serving surface, the tag@digest image pin, and the attack-surface row.
  6. The ruling withholds ``service:apex`` itself — the page must not narrate
     its own serving infrastructure, and the manifest id becoming a
     service-name token means the leak check forbids the word from every
     emitted file (pinned in test_apex_public_projection.py's clean-surface
     sweep, which now runs with 'apex' in the forbidden set).

CI-safe: pure source scan + subprocess against a tmp mirror. No Docker, no
network, no live host, and the committed ruling file is never modified.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import re
import shutil
import subprocess
import sys

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
APEX = REPO / "files" / "anatomy" / "apex"
ROLE = REPO / "roles" / "pazny.apex"


def _load_projection():
    spec = importlib.util.spec_from_file_location("apex_projection_sig", APEX / "projection.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P = _load_projection()


@pytest.fixture(scope="module")
def ruling():
    return P.load_ruling()


# ---------------------------------------------------------------------------
# 1. serve_gate — mutation-verified both directions, committed file untouched
# ---------------------------------------------------------------------------

def test_serve_gate_refuses_a_proposed_ruling(ruling):
    mutated = copy.deepcopy(ruling)
    mutated["status"] = "PROPOSED"
    mutated["signed_by"] = None
    with pytest.raises(P.GateError, match="not SIGNED"):
        P.serve_gate(mutated)


def test_serve_gate_refuses_signed_with_nobody(ruling):
    mutated = copy.deepcopy(ruling)
    mutated["status"] = "SIGNED"
    for nobody in (None, "", "   "):
        mutated["signed_by"] = nobody
        with pytest.raises(P.GateError, match="signed_by"):
            P.serve_gate(mutated)


def test_serve_gate_passes_a_signed_ruling(ruling):
    mutated = copy.deepcopy(ruling)
    mutated["status"] = "SIGNED"
    mutated["signed_by"] = "An Operator"
    P.serve_gate(mutated)   # must not raise


def test_serve_gate_refuses_lowercase_or_lookalike_status(ruling):
    """'signed', 'Signed', 'SIGNED ' are not signatures — the exact enum only."""
    mutated = copy.deepcopy(ruling)
    mutated["signed_by"] = "An Operator"
    for lookalike in ("signed", "Signed", "SIGNED ", "APPROVED", True):
        mutated["status"] = lookalike
        with pytest.raises(P.GateError):
            P.serve_gate(mutated)


# ---------------------------------------------------------------------------
# 2. the converge command, end-to-end, in a throwaway mirror
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def mirror(tmp_path_factory):
    """A minimal repo mirror: <root>/files/anatomy/apex + <root>/state, so
    projection.py's REPO = parents[2] resolution lands inside the tmp dir."""
    root = tmp_path_factory.mktemp("apexmirror")
    apex_dir = root / "files" / "anatomy" / "apex"
    apex_dir.parent.mkdir(parents=True)
    shutil.copytree(APEX, apex_dir, ignore=shutil.ignore_patterns("dist", "__pycache__"))
    (root / "state").mkdir()
    shutil.copy2(REPO / "state" / "anatomy-graph.json", root / "state" / "anatomy-graph.json")
    return apex_dir


def _run_build(apex_dir: pathlib.Path, out: pathlib.Path):
    return subprocess.run(
        [sys.executable, str(apex_dir / "build.py"), "--require-signed",
         "--out", str(out)],
        capture_output=True, text=True, timeout=120,
    )


def test_converge_command_refuses_and_writes_nothing_while_proposed(mirror, tmp_path):
    ruling_path = mirror / "ruling.yml"
    doc = yaml.safe_load(ruling_path.read_text())
    doc["status"] = "PROPOSED"
    doc["signed_by"] = None
    ruling_path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))

    out = tmp_path / "www"
    r = _run_build(mirror, out)
    assert r.returncode == 4, f"expected exit 4 (serving refused), got {r.returncode}: {r.stderr}"
    assert "NOT SIGNED" in r.stderr
    assert not out.exists(), "an unsigned ruling must not produce a web root"


def test_converge_command_serves_once_signed(mirror, tmp_path):
    ruling_path = mirror / "ruling.yml"
    doc = yaml.safe_load(ruling_path.read_text())
    doc["status"] = "SIGNED"
    doc["signed_by"] = "Mutation Test Signer"
    ruling_path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))

    out = tmp_path / "www"
    r = _run_build(mirror, out)
    assert r.returncode == 0, f"signed ruling must build: rc={r.returncode}: {r.stderr}"
    assert (out / "index.html").exists()
    assert (out / "public-anatomy.json").exists()


def test_the_committed_ruling_was_not_touched_by_this_file(ruling):
    """The mutation fixtures work on copies; the committed status is whatever
    the operator last set it to. This asserts only self-consistency: SIGNED
    requires a signer, PROPOSED requires none."""
    committed = yaml.safe_load((APEX / "ruling.yml").read_text())
    assert committed["status"] in ("PROPOSED", "SIGNED")
    if committed["status"] == "SIGNED":
        assert str(committed.get("signed_by") or "").strip(), \
            "committed ruling says SIGNED with no signed_by"


# ---------------------------------------------------------------------------
# 3+4. the role gates before it renders, and the gate has no side door
# ---------------------------------------------------------------------------

def _role_tasks() -> list[dict]:
    return yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())


def test_role_asserts_signature_before_anything_renders():
    tasks = _role_tasks()
    names = [t.get("name", "") for t in tasks]

    def idx(fragment):
        hits = [i for i, n in enumerate(names) if fragment in n]
        assert hits, f"no task matching {fragment!r} in roles/pazny.apex/tasks/main.yml: {names}"
        return hits[0]

    gate_i = idx("REFUSE")
    build_i = idx("Build the public site")
    override_i = idx("compose override")
    assert gate_i < build_i < override_i, (
        "the signature gate must run before the build, and the build before "
        f"the compose-override render; got order {names}"
    )

    gate = tasks[gate_i]
    conditions = " ".join((gate.get("ansible.builtin.assert") or gate.get("assert"))["that"])
    assert "'SIGNED'" in conditions and "signed_by" in conditions


def test_role_build_command_requires_the_signature():
    tasks = _role_tasks()
    build = next(t for t in tasks if "Build the public site" in t.get("name", ""))
    argv = (build.get("ansible.builtin.command") or build.get("command"))["argv"]
    assert "--require-signed" in argv, (
        "the role's build invocation lost --require-signed — the Ansible assert "
        "alone would then be the only gate, and a task reorder could open the door"
    )


def test_build_script_has_no_ruling_override_flag():
    src = (APEX / "build.py").read_text()
    assert "--ruling" not in src, (
        "build.py grew a flag to read a different ruling file — the deploy gate "
        "must read the committed ruling or nothing"
    )


# ---------------------------------------------------------------------------
# 5. the prepared-but-inert route: manifest, auth mode, pin, read-only serve
# ---------------------------------------------------------------------------

def test_manifest_routes_apex_through_the_exposure_gates_population():
    manifest = yaml.safe_load((REPO / "state" / "manifest.yml").read_text())
    apex = next((s for s in manifest["services"] if s["id"] == "apex"), None)
    assert apex, "apex left state/manifest.yml"
    assert apex.get("domain_var") == "apex_domain" and apex.get("port_var") == "apex_port", (
        "apex must be routed via the manifest auto-derivation (domain_var + "
        "port_var) — a traefik_extra_routers entry would bypass "
        "test_traefik_exposure_justified.py's population"
    )
    assert apex.get("install_flag") == "install_apex"
    assert apex.get("rbac_tier") == 4


def test_auth_mode_none_with_a_justification_field():
    tvars = yaml.safe_load((REPO / "roles/pazny.traefik/vars/main.yml").read_text())
    assert tvars["traefik_auth_modes"].get("apex") == "none"
    assert "apex" not in (tvars.get("traefik_skip_ids") or [])
    reason = (tvars.get("traefik_auth_none_justification") or {}).get("apex", "")
    assert len(reason.strip()) >= 40, "REM-144 rule: an ungated route needs a justification FIELD"
    assert (tvars.get("traefik_container_upstreams") or {}).get("apex", {}).get("port") == 80


def test_the_serving_surface_is_read_only_and_static():
    tpl = (ROLE / "templates" / "compose.yml.j2").read_text()
    assert "read_only: true" in tpl
    assert re.search(r"apex_web_root \}\}:/usr/share/nginx/html:ro", tpl), \
        "the web root bind lost its :ro"
    assert "apex-nginx.conf:/etc/nginx/conf.d/default.conf:ro" in tpl
    # no writable named volume / bind may sneak in: every volume line ends :ro
    volumes = [ln.strip() for ln in tpl.splitlines()
               if ln.strip().startswith("- ") and ":/" in ln and "tmpfs" not in ln]
    mounts = [v for v in volumes if "/usr/share" in v or "/etc/nginx" in v]
    assert mounts and all(v.endswith(":ro") for v in mounts), mounts
    assert "gated_net" in tpl, "apex left the SEC-02 gated_net posture"


def test_the_image_pin_carries_tag_and_digest():
    text = (REPO / "default.config.yml").read_text()
    m = re.search(r'^apex_version:\s*"([^"]+)"', text, re.M)
    assert m, "apex_version left default.config.yml (the winning layer)"
    assert re.fullmatch(r"[0-9.]+-alpine(?:[a-z0-9.-]*)?@sha256:[0-9a-f]{64}", m.group(1)), (
        f"apex_version must be tag@digest (the tag says what we meant, the "
        f"digest says what we get): {m.group(1)!r}"
    )


def test_the_attack_surface_records_the_public_path():
    doc = json.loads((REPO / "docs/llm/security/attack-surface.json").read_text())
    paths = doc["attack_surface_map"]["web_ui_unauthenticated_paths"]["paths"]
    apex_rows = [p for p in paths if p.get("service") == "apex"]
    assert apex_rows, "apex is missing from web_ui_unauthenticated_paths"
    assert any("by design" in p.get("auth", "") for p in apex_rows)


# ---------------------------------------------------------------------------
# 6. the page must not narrate its own server
# ---------------------------------------------------------------------------

def test_the_ruling_withholds_the_apex_itself(ruling):
    assert ruling["nodes"].get("service:apex") == "withheld", (
        "service:apex must stay withheld — publishing it would name the "
        "serving infrastructure of the very page a stranger is reading"
    )
