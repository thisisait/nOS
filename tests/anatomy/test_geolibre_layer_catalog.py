"""Anatomy gate — GeoLibre's layer catalog, the atlas smoke row and the refresh job.

GeoLibre v3.2.0 reads GEOLIBRE_SERVICES_FILE once at boot (docker/entrypoint.sh at
rev aa28b2a) and refuses to start on an invalid entry. So:

  1. the catalog is RENDERED from `geolibre_layers` (default.config.yml) — the
     template is rendered and the JSON parsed here, against the upstream rules;
  2. every declared layer carries a licence note with an https source, and every
     URL is https (the page is https; mixed content never loads);
  3. atlas.<tenant> smokes as what forward_auth returns to an anonymous probe;
  4. the atlas-refresh Pulse job survives BOTH token lists and the real validator.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import jinja2
import jinja2.nativetypes
import yaml

from pulse.runners.subprocess import validate_command

REPO = Path(__file__).resolve().parents[2]
ROLE = REPO / "roles/pazny.geolibre"
PLUGIN = REPO / "files/anatomy/plugins/geolibre-base/plugin.yml"
KINDS = ("wms", "wfs", "wmts", "xyz", "arcgis", "csw")  # entrypoint.sh service_kinds
URL_FIELDS = ("url", "endpoint")


def _declared(**over) -> list[dict]:
    """geolibre_layers with its Jinja resolved the way Ansible does (native types)."""
    d = yaml.safe_load((REPO / "default.config.yml").read_text())
    ctx = {"maps_domain": "maps.dev.local", "install_offline_maps": True, **over}
    env = jinja2.nativetypes.NativeEnvironment(undefined=jinja2.StrictUndefined)

    def res(v):
        if isinstance(v, str) and "{{" in v:
            return env.from_string(v).render(**ctx)
        if isinstance(v, dict):
            return {k: res(x) for k, x in v.items()}
        if isinstance(v, list):
            return [res(x) for x in v]
        return v

    return res(d["geolibre_layers"])


def _rendered(**over) -> dict:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    text = env.from_string((ROLE / "templates/services.json.j2").read_text()).render(
        geolibre_layers=_declared(**over))
    return json.loads(text)


def test_catalog_is_rendered_from_the_declaration():
    cat = _rendered()
    assert isinstance(cat.get("services"), list) and cat["services"], "no services array"
    ids = [s["id"] for s in cat["services"]]
    assert len(ids) == len(set(ids)), f"duplicate ids: {ids}"
    for s in cat["services"]:
        # The upstream boot validator, rule by rule.
        assert s["id"].strip() and s["name"].strip(), s
        assert s["kind"] in KINDS, s
        assert isinstance(s.get("category", ""), str)
        assert isinstance(s["fields"], dict) and s["fields"], s
        assert all(isinstance(v, (str, int, float, bool)) for v in s["fields"].values()), s
    assert ids == [layer["id"] for layer in _declared()], "catalog drifted from the declaration"
    # The off flag drops the tileserver entry instead of listing a dead host.
    assert "nos-basemap" in ids
    assert "nos-basemap" not in [s["id"] for s in _rendered(install_offline_maps=False)["services"]]


def test_the_role_renders_and_mounts_the_catalog():
    tasks = (ROLE / "tasks/main.yml").read_text()
    assert "services.json.j2" in tasks, "the role never renders the catalog"
    compose = (ROLE / "templates/compose.yml.j2").read_text()
    assert "GEOLIBRE_SERVICES_FILE" in compose
    assert "/catalog:/etc/geolibre:ro" in compose, "mount the catalog DIR read-only (a file bind breaks on rename)"


def test_every_layer_has_a_licence_and_https():
    for layer in _declared():
        lid = layer["id"]
        assert layer.get("licence", "").strip(), f"{lid}: no licence note"
        assert str(layer.get("licence_url", "")).startswith("https://"), f"{lid}: licence source must be an https URL"
        urls = [layer["fields"][k] for k in URL_FIELDS if k in layer["fields"]]
        assert urls, f"{lid}: no url/endpoint field"
        assert all(u.startswith("https://") for u in urls), f"{lid}: not https: {urls}"
        assert "key=" not in json.dumps(layer["fields"]).lower(), f"{lid}: a keyed service"


def test_atlas_smokes_as_forward_auth_answers():
    cat = yaml.safe_load((REPO / "state/smoke-catalog.yml").read_text())["smoke_endpoints"]
    row = next((e for e in cat if e["id"] == "geolibre"), None)
    assert row, "no smoke row for atlas (the manifest auto-row accepts a 200 — a leak)"
    assert row["url"] == "https://{{ geolibre_domain }}/"
    assert row["expect"] == [302] and row["expect_strict"] == [302], row
    assert "install_geolibre" in row["when"]


def _refresh_job() -> dict:
    jobs = yaml.safe_load(PLUGIN.read_text())["pulse"]["jobs"]
    return next(j for j in jobs if j["name"] == "atlas-refresh")


def test_refresh_job_passes_both_token_lists_and_the_validator(monkeypatch):
    job = _refresh_job()
    env = {"NOS_PLAYBOOK_DIR": "/Users/op/nOS", "NOS_GEOLIBRE_DATA_DIR": "/Users/op/nos/geolibre/data",
           "NOS_ATLAS_SRC_DIR": "/Users/op/projects/nos-atlas"}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    spec = importlib.util.spec_from_file_location(
        "_cat", REPO / "files/anatomy/scripts/discover-pulse-catalog.py")
    cat = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cat)
    expanded = cat._expand(job, cat._build_substitutions())
    assert "{{" not in json.dumps(expanded), f"a token the catalog does not render: {expanded}"
    wing = (REPO / "roles/pazny.wing/tasks/post.yml").read_text()
    for name in ("NOS_GEOLIBRE_DATA_DIR", "NOS_ATLAS_SRC_DIR"):
        assert f"{name}:" in wing, f"{name} is not exported by wing post.yml"
    monkeypatch.setenv("NOS_REPO_ROOT", "/Users/op/nOS")
    monkeypatch.setenv("HOME", "/Users/op")
    validate_command(expanded["command"], expanded.get("args") or [])


def _tool():
    spec = importlib.util.spec_from_file_location("atlas_refresh", REPO / "tools/atlas-refresh.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_refresh_runs_the_nos_atlas_job_contract(tmp_path, monkeypatch):
    """nos-atlas README "nOS job contract": snapshot script, then build.ts --out <root>/live."""
    atlas = tmp_path / "nos-atlas"
    (atlas / "fixtures").mkdir(parents=True)
    (atlas / "fixtures/keap-taxonomy.json").write_text("{}")
    tool = _tool()
    calls = []

    class Done:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(tool.subprocess, "run", lambda argv, **kw: calls.append((argv, kw)) or Done())
    assert tool.main(["--data-dir", str(tmp_path / "data"), "--atlas-src", str(atlas)]) == 0
    (snap, kw1), (gen, kw2) = calls
    assert all(isinstance(x, str) for x in snap + gen), "argv lists, never a shell string"
    assert kw1["cwd"] == kw2["cwd"] == atlas
    assert snap[1] == "scripts/snapshot-from-readers.mjs" and snap[snap.index("--nos") + 1] == str(REPO)
    assert gen[1] == "src/generator/build.ts"
    assert gen[gen.index("--snapshot") + 1] == snap[snap.index("--out") + 1]
    assert gen[gen.index("--out") + 1] == str(tmp_path / "data/plugins/nos-atlas/live")


def test_refresh_is_a_noop_when_geolibre_is_off(capsys):
    assert _tool().main(["--data-dir", "", "--atlas-src", ""]) == 0
    assert "off" in capsys.readouterr().out
