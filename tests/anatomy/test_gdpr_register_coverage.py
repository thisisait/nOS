"""Anatomy CI gate — GDPR Article-30 register coverage + integrity.

C3 (2026-05-25) connected the per-plugin `gdpr:` blocks (loader-validated but
previously never ingested) to the Article-30 register surfaces. Before C3 the
live `gdpr_processing` table + the DPA register covered only the 4 Tier-2 apps;
the ~50 core services were dark. This gate pins the contract so the register
can't silently regress to partial coverage:

  1. Every plugin carrying a `gdpr:` block yields exactly one Article-30
     record (no service drops out of the register).
  2. Every record is Article-30-complete: non-empty id/name/purpose, a valid
     Art. 6(1) legal basis, non-empty data categories + subjects, a retention
     decision, and a storage location.
  3. The committed `state/dpa-register.md` is byte-identical to a fresh render
     (the DPO-facing artifact can't go stale without CI catching it).
"""

from __future__ import annotations

import pathlib

import pytest

# tests/conftest.py adds files/anatomy/ to sys.path.
from module_utils import load_plugins, nos_gdpr  # type: ignore  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGINS_ROOT = REPO / "files" / "anatomy" / "plugins"

ARTICLE6_BASES = {
    "consent", "contract", "legal_obligation",
    "vital_interests", "public_task", "legitimate_interests",
}


def _core_records() -> list[dict]:
    return nos_gdpr.records_from_plugins(PLUGINS_ROOT)


def _plugins_with_gdpr() -> list[load_plugins.Plugin]:
    return [p for p in load_plugins.discover(PLUGINS_ROOT) if p.manifest.get("gdpr")]


def test_every_gdpr_plugin_yields_one_record():
    """Coverage parity — no plugin with a gdpr block drops out of the register."""
    plugins = {p.name for p in _plugins_with_gdpr()}
    records = _core_records()
    record_sources = {r["source_plugin"] for r in records}
    assert plugins == record_sources, (
        f"register/plugin mismatch — "
        f"missing from register: {sorted(plugins - record_sources)}; "
        f"phantom records: {sorted(record_sources - plugins)}"
    )
    # one record per plugin, ids unique
    ids = [r["id"] for r in records]
    assert len(ids) == len(set(ids)) == len(plugins)


def test_ids_use_svc_prefix():
    for r in _core_records():
        assert r["id"].startswith("svc_"), r["id"]


@pytest.mark.parametrize("rec", _core_records(), ids=lambda r: r["id"])
def test_record_is_article30_complete(rec):
    assert rec["id"] and rec["name"], "id + name required"
    assert rec["purpose"].strip(), "purpose must be non-empty (default-filled if absent)"
    assert rec["legal_basis"] in ARTICLE6_BASES, \
        f"{rec['legal_basis']!r} not an Art. 6(1) basis"
    assert isinstance(rec["data_categories"], list) and rec["data_categories"], \
        "at least one data category"
    assert isinstance(rec["data_subjects"], list) and rec["data_subjects"], \
        "at least one data subject"
    # retention_days present (int incl. -1 indefinite); None only if explicitly null
    assert "retention_days" in rec
    assert rec["storage_location"].strip(), "storage location required"
    assert rec["transfers_outside_eu"] in (0, 1)
    assert isinstance(rec["security_measures"], list) and rec["security_measures"]


# Columns bin/upsert-gdpr.php reads off the JSON (its $copyKeys + the two it
# coerces). The live Tier-1 ingest (roles/pazny.wing/tasks/post.yml) pipes each
# record straight to that tool, so the mapper must always carry every one — a
# silent drop would leave the gdpr_processing row with a NULL NOT-NULL column.
UPSERT_COLUMNS = {
    "name", "purpose", "legal_basis", "data_categories", "data_subjects",
    "processors", "security_measures", "retention_days", "storage_location",
    "transfers_outside_eu",
}


@pytest.mark.parametrize("rec", _core_records(), ids=lambda r: r["id"])
def test_record_carries_all_upsert_columns(rec):
    assert UPSERT_COLUMNS.issubset(rec.keys()), \
        f"{rec['id']} missing upsert columns: {sorted(UPSERT_COLUMNS - rec.keys())}"


# ── Authored-purpose gate for real-subject-PII services ──────────────────────
# nos_gdpr default-fills a generic purpose for any plugin whose `gdpr.purpose`
# is absent, flagging it `purpose_generated=True`. Generic boilerplate is
# acceptable for operator-only / infra activities, but NOT for an activity that
# processes real data-subject PII: Art-30(1)(b) requires a *specific* purpose,
# and a DPO can't assess proportionality against a placeholder. So any plugin
# whose `data_subjects` name end_users (the canonical real-subject token) MUST
# carry an author-provided purpose. The set of end_users-bearing records is
# discovered dynamically, so a new such service can't silently ship with
# boilerplate and keep the gate green.
_REAL_SUBJECT_TOKEN = "end_users"


def _end_user_records() -> list[dict]:
    return [r for r in _core_records() if _REAL_SUBJECT_TOKEN in r["data_subjects"]]


def test_end_user_services_exist():
    """Sanity: the dynamic discovery actually finds the real-subject cohort
    (guards against a token rename silently emptying the parametrization and
    turning the authored-purpose gate into a vacuous pass)."""
    assert _end_user_records(), \
        f"no records carry data_subjects[{_REAL_SUBJECT_TOKEN!r}] — token renamed?"


@pytest.mark.parametrize("rec", _end_user_records(), ids=lambda r: r["id"])
def test_end_user_service_has_authored_purpose(rec):
    """Art-30(1)(b): a service processing end_user PII needs a specific,
    author-provided purpose — not the nos_gdpr generic boilerplate."""
    assert rec.get("purpose_generated") is False, (
        f"{rec['id']} processes end_users ({rec['data_subjects']}) but ships NO "
        f"explicit gdpr.purpose — nos_gdpr auto-filled generic boilerplate. "
        f"Author a specific purpose in the plugin's gdpr block "
        f"(operators-only / infra services may keep the generated default)."
    )


_GDPR_ENV = ("GDPR_CONTROLLER_NAME", "GDPR_DPO_NAME", "GDPR_DPO_CONTACT")


def _load_tool():
    import importlib.util

    tool_path = REPO / "tools" / "gdpr-dpa-register.py"
    spec = importlib.util.spec_from_file_location("gdpr_dpa_register", tool_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_committed_dpa_register_is_current(monkeypatch):
    """The DPO-facing markdown must match a fresh render of the source blocks.
    Clear the GDPR_* controller vars first — the committed register is the
    inert/placeholder form, so a gov operator who exported them must NOT hit a
    spurious 'stale' red (the byte-identity gate assumes GDPR_* unset)."""
    for v in _GDPR_ENV:
        monkeypatch.delenv(v, raising=False)
    mod = _load_tool()
    out = REPO / "state" / "dpa-register.md"
    assert out.exists(), "state/dpa-register.md missing — run tools/gdpr-dpa-register.py"
    fresh = mod.render(nos_gdpr.all_records(REPO))
    assert out.read_text() == fresh, (
        "state/dpa-register.md is stale — run "
        "`python3 tools/gdpr-dpa-register.py` and commit."
    )


def test_controller_block_inert_without_env(monkeypatch):
    """Art-30(1)(a) block renders deterministic placeholders when GDPR_* unset."""
    for v in _GDPR_ENV:
        monkeypatch.delenv(v, raising=False)
    blob = "\n".join(_load_tool()._controller_lines())
    assert "## Controller & DPO (Art. 30(1)(a))" in blob
    assert "_(unset — export GDPR_CONTROLLER_NAME)_" in blob
    assert "_(unset — export GDPR_DPO_NAME)_" in blob
    assert "_(unset — export GDPR_DPO_CONTACT)_" in blob


def test_controller_block_populates_from_env(monkeypatch):
    """Exported GDPR_* values flow into the Art-30(1)(a) block."""
    monkeypatch.setenv("GDPR_CONTROLLER_NAME", "Acme Úřad")
    monkeypatch.setenv("GDPR_DPO_NAME", "Jan Novák")
    monkeypatch.setenv("GDPR_DPO_CONTACT", "dpo@acme.gov.cz")
    blob = "\n".join(_load_tool()._controller_lines())
    assert "Acme Úřad" in blob and "Jan Novák" in blob and "dpo@acme.gov.cz" in blob
    assert "unset —" not in blob
