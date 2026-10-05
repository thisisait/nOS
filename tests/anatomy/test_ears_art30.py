"""Ears Art-30: the register row is the deploy gate, and it says what the code does.

install_ears is on by default and the 2026-10-02 device study found it had no
Art-30 row. Operator decision 2026-10-03: no transcripts by default. This pins:
a complete gdpr block in ears-base (0 = transient is the honest default); the
converge refuses install_ears without it; DSAR maps and the register carry
svc_ears; the "audio never stored" claim is true in the listener's AST; the
plist sentence tells the truth in both modes. Policy: docs/compliance/ears.md.
"""
from __future__ import annotations

import ast
import pathlib

import jinja2
import yaml

from module_utils.nos_app_parser import GDPR_LEGAL_BASES, REQUIRED_GDPR  # type: ignore

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGIN = REPO / "files/anatomy/plugins/ears-base/plugin.yml"
DEFAULTS = REPO / "roles/pazny.ears/defaults/main.yml"
LISTENER = REPO / "files/anatomy/ears/ears-listen.py"
PLIST = REPO / "roles/pazny.ears/templates/ears-app-info.plist.j2"
MAIN = REPO / "main.yml"
DOC = REPO / "docs/compliance/ears.md"
ERASURE = REPO / "state/gdpr-erasure-map.yml"
EXPORT = REPO / "state/gdpr-export-map.yml"
REGISTER = REPO / "state/dpa-register.md"


def _ansible_env():
    """jinja2 with the one Ansible filter these templates use."""
    import jinja2
    env = jinja2.Environment()
    env.filters["bool"] = lambda v: str(v).strip().lower() in ("1", "true", "yes", "on")
    return env


def _plugin() -> dict:
    return yaml.safe_load(PLUGIN.read_text(encoding="utf-8")) or {}


def _defaults() -> dict:
    return yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))


def gdpr_block_is_complete(gdpr: dict) -> list[str]:
    """The app parser's REQUIRED_GDPR + enum. 0 is allowed: it means transient."""
    errs = [f"gdpr.{k} missing" for k in REQUIRED_GDPR if k not in gdpr]
    if gdpr.get("legal_basis") not in GDPR_LEGAL_BASES:
        errs.append(f"legal_basis {gdpr.get('legal_basis')!r} not in enum")
    if not str(gdpr.get("purpose", "")).strip():
        errs.append("purpose empty")
    if not isinstance(gdpr.get("retention_days"), int):
        errs.append("retention_days must be a declared integer (0 = transient)")
    if "bystanders" not in (gdpr.get("data_subjects") or []):
        errs.append("a microphone in a room hears bystanders; the record must say so")
    return errs


def audio_is_never_at_rest(src: str) -> list[str]:
    """The wav exists inside one call: a try whose finally unlinks it."""
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_transcribe_pcm"), None)
    if fn is None:
        return ["_transcribe_pcm is gone"]
    finals = [n for n in ast.walk(fn) if isinstance(n, ast.Try) and n.finalbody]
    unlinks = [c for t in finals for c in ast.walk(ast.Module(body=t.finalbody, type_ignores=[]))
               if isinstance(c, ast.Call) and ast.unparse(c.func) in ("os.unlink", "os.remove")]
    return [] if unlinks else ["the segment wav is not deleted in a finally"]


def test_plugin_carries_a_complete_art30_block():
    assert PLUGIN.is_file(), "ears-base/plugin.yml is the Art-30 row"
    p = _plugin()
    assert gdpr_block_is_complete(p.get("gdpr") or {}) == []
    assert (p.get("requires") or {}).get("feature_flag") == "install_ears"
    assert p["gdpr"]["processors"] == [], "ASR is on-device; a processor here would be a new fact"
    assert _defaults()["ears_asr_model"] in p["gdpr"]["purpose"], (
        "the record must name the model that actually transcribes")


def test_the_gate_is_red_on_a_broken_block():
    assert gdpr_block_is_complete({}) and gdpr_block_is_complete({"legal_basis": "vibes"})
    good = _plugin()["gdpr"]
    assert gdpr_block_is_complete({**good, "retention_days": "0"})
    assert gdpr_block_is_complete({**good, "data_subjects": ["operators"]})


def test_audio_claim_matches_the_code():
    assert audio_is_never_at_rest(LISTENER.read_text(encoding="utf-8")) == []
    assert audio_is_never_at_rest("def _transcribe_pcm(m, p):\n    return m.transcribe(p)\n")
    assert _defaults()["ears_dump_segments"] == 0, "wav diagnostic must be off by default"
    assert 'os.environ.get("EARS_DUMP_SEGMENTS", "0")' in LISTENER.read_text()


def test_converge_refuses_the_flag_without_the_block():
    tasks = yaml.safe_load(MAIN.read_text(encoding="utf-8"))[0]["tasks"]
    names = [t.get("name", "") for t in tasks]
    gate = next(i for i, n in enumerate(names) if n.startswith("[Art-30] Refuse the ears"))
    role = next(i for i, n in enumerate(names) if n.startswith("Ears — the speech organ"))
    assert gate < role, "the assert must run before the role import"
    t = tasks[gate]
    assert "install_ears" in str(t["when"])
    that = " ".join(t["ansible.builtin.assert"]["that"])
    for key in REQUIRED_GDPR:
        assert key in that, f"assert does not check gdpr.{key}"
    assert "bystanders" in that


def test_dsar_maps_and_register_carry_the_service():
    for path in (ERASURE, EXPORT):
        entries = {e["id"]: e for e in yaml.safe_load(path.read_text())["services"]}
        e = entries.get("svc_ears")
        assert e, f"{path.name} lacks svc_ears"
        assert e["flag"] == "install_ears" and e["method"] == "manual"
        assert "turns" in e["note"] and "caddy-sessions" in e["note"]
    assert "svc_ears" in REGISTER.read_text(encoding="utf-8")


def test_policy_doc_matches_the_register_row_and_defaults():
    text = DOC.read_text(encoding="utf-8")
    g, d = _plugin()["gdpr"], _defaults()
    assert f"**{g['retention_days']} days**" in text
    assert f"**{d['ears_retention_days']} days**" in text, "the kept-mode horizon must be in the doc"
    assert g["legal_basis"] in text
    assert "docs/compliance/ears.md" in (REPO / "docs/systems/ears/README.md").read_text()


def test_the_microphone_prompt_tells_the_truth_in_both_modes():
    tpl = _ansible_env().from_string(PLIST.read_text(encoding="utf-8"))
    base = {**_defaults(), "ears_app_name": "x", "ears_app_bundle_id": "x"}
    off = tpl.render({**base, "ears_keep_transcripts": False})
    on = tpl.render({**base, "ears_keep_transcripts": True})
    assert "transcripts are not stored" in off and "kept" not in off.split("Audio")[1]
    assert f"kept {base['ears_retention_days']} days" in on
