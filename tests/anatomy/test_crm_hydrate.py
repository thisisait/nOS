"""crm-hydrate is a hydrator organelle, not another FOSS login screen.

RETRO-RED: before crm-hydrate-base + digest-import-doli, Dolibarr was a
container with no Pulse/Digest/Cortex tendon — the Espo/Firefly shape.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGIN = REPO / "files/anatomy/plugins/crm-hydrate-base/plugin.yml"
IMPORTER = REPO / "state/digest-importers/doli-party.importer.yml"
TOOL = REPO / "tools/digest-import-doli.py"
SKILL = REPO / "files/anatomy/skills/nos-backoffice/SKILL.md"
FIXTURE = REPO / "tests/fixtures/doli-party.json"
DOLIBARR = REPO / "files/anatomy/plugins/dolibarr-base/plugin.yml"


def test_the_hydrator_plugin_is_a_job_not_a_second_crm():
    man = yaml.safe_load(PLUGIN.read_text(encoding="utf-8"))
    assert "scheduled-job" in man["type"]
    assert "service" not in man["type"]
    assert man["requires"]["feature_flag"] == "install_dolibarr"
    jobs = man["pulse"]["jobs"]
    assert len(jobs) == 1
    job = jobs[0]
    assert job["name"] == "hydrate-parties"
    assert "--absorb" in job["args"]
    targets = [w["target"] for w in job["writes"]]
    assert targets == ["table:party", "table:party-tax-identity"]
    # Firefly/Espo failure mode: copy the desk ledger into KEAP books.
    assert "table:invoice" not in targets
    assert "table:posting" not in targets


def test_the_books_are_not_a_doli_or_firefly_projection():
    inv = yaml.safe_load(
        (REPO / "state" / "keap-tables" / "invoice.table.yml").read_text(encoding="utf-8")
    )
    source = next(c for c in inv["schema"]["columns"] if c["key"] == "source")
    assert source["options"] == ["isdoc", "vision"]
    tool = TOOL.read_text(encoding="utf-8")
    assert "llx_facture" not in tool
    assert "llx_societe" in tool


def test_the_desk_plugin_does_not_claim_to_hydrate():
    man = yaml.safe_load(DOLIBARR.read_text(encoding="utf-8"))
    assert not (man.get("pulse") or {}).get("jobs")


def test_importer_manifest_matches_the_running_class():
    dec = yaml.safe_load(IMPORTER.read_text(encoding="utf-8"))
    assert dec["name"] == "doli-party"
    assert dec["egress"] == []
    import importlib.util
    spec = importlib.util.spec_from_file_location("digest_import_doli", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.DoliPartyImporter.name == "doli-party"


def test_hydrator_gates_a_fixture_and_skips_rows_without_ico():
    proc = subprocess.run(
        [sys.executable, str(TOOL), "--from-json", str(FIXTURE), "--fixture-mode"],
        cwd=REPO, capture_output=True, text=True, timeout=20)
    assert proc.returncode == 0, proc.stderr
    assert "skip" in proc.stderr and "No Ico" in proc.stderr
    bundle = yaml.safe_load(proc.stdout)
    parties = bundle["deterministic"]["party"]
    assert len(parties) == 1
    assert parties[0]["notes"] == "nos:doli:12"
    assert parties[0]["legal_name"] == "Alfa s.r.o."


def test_the_skill_forbids_vendor_rest():
    text = SKILL.read_text(encoding="utf-8")
    assert "When NOT to use" in text
    assert "Do not curl Dolibarr" in text
    assert "/api/index.php/" in text
    assert "espo-party-sync" in text
