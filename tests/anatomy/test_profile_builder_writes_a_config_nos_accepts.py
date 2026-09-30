"""The profile builder is a static page whose every fact comes from the
artifacts at build time, and whose JS is RUN here under node — a page that
lists services from prose would drift the day a flag is added.

  1. the data derives every install_* flag default.config.yml declares, every
     profile that carries an `axis:` header, and every step field is a variable
     the config declares;
  2. the merge (default → service-set → use-case → policy → environment →
     constraint → mail → your toggles) reproduces a profile's own flags;
  3. the config.yml it writes parses as YAML, holds only overrides, and never
     the password prefix;
  4. the RAM estimate is the sum of the compose templates' rendered mem_limit
     (gitlab's declared limit moves it by exactly that much), the data figure
     is the one assumption table applied per manifest category;
  5. built with an image lock, a service whose image the lock lacks is OFF and
     says why, even when a profile turns it on; without a lock nothing is
     blocked and image bytes are unknown, not zero.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
CONFIG_TEXT = (REPO / "default.config.yml").read_text()
_spec = importlib.util.spec_from_file_location("pb", REPO / "tools/profile-builder-build.py")
pb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pb)
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(not NODE, reason="node is how the page's own logic is executed")


def test_the_data_is_the_artifacts_not_a_list():
    data = pb.build()
    declared = set(re.findall(r"^(install_[a-z0-9_]+):", CONFIG_TEXT, re.M))
    assert {f["key"] for f in data["flags"]} == declared
    axes_on_disk = {p.stem for p in (REPO / "profiles").glob("*.yml")
                    if re.search(r"^# axis: ", p.read_text(), re.M)}
    assert {p["id"] for p in data["profiles"]} == axes_on_disk
    assert all(p["axis"] in data["axes"] for p in data["profiles"]), "a profile declares an axis the page has no step for"
    assert all(f["section"] for f in data["flags"])
    every_var = set(re.findall(r"^([a-z_]+):", CONFIG_TEXT, re.M))
    for step in data["steps"]:
        for f in step["fields"]:
            assert f["key"] in every_var, f"step field {f['key']} is not a variable default.config.yml declares"
            assert f["hint"], f"{f['key']} has no plain-language line"
    assert [s["id"] for s in data["steps"]] == ["machine", "domain", "people", "services", "backup", "review"]


def _node(script: str, data: dict | None = None) -> dict:
    tpl = (REPO / "tools/profile-builder/index.html.tpl").read_text()
    logic = re.search(r'<script id="logic">(.*?)</script>', tpl, re.S).group(1)
    out = subprocess.run([NODE, "-e", logic + f"\nconst DATA={json.dumps(data or pb.build())};\n" + script],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@needs_node
def test_picking_a_profile_reproduces_its_flags():
    res = _node('''
      const on = mergeFlags(DATA, {"service-set": "dev-minimal"}, "none", {});
      const prof = DATA.profiles.find(p => p.id === "dev-minimal");
      const bad = Object.entries(prof.flags).filter(([k, v]) => on[k] !== v);
      const layered = mergeFlags(DATA, {"service-set": "dev-minimal", "use-case": "praxis"}, "stalwart", {install_kiwix: !prof.flags.install_kiwix});
      console.log(JSON.stringify({bad, stalwart: layered.install_smtp_stalwart, mailpit: layered.install_mailpit,
        manual_wins: layered.install_kiwix === !prof.flags.install_kiwix,
        praxis_wins: Object.entries(DATA.profiles.find(p => p.id === "praxis").flags).every(([k, v]) => layered[k] === v)}));
    ''')
    assert res["bad"] == [], f"picking dev-minimal did not reproduce it: {res['bad']}"
    assert res["stalwart"] is True and res["mailpit"] is False, "the mail choice must outrank the profiles"
    assert res["praxis_wins"], "use-case must layer over service-set"
    assert res["manual_wins"], "a toggle the person made must be the last word"


@needs_node
def test_the_written_config_is_yaml_overrides_only_and_no_secret():
    res = _node('''
      const picks = {"service-set": "dev-minimal", "policy": "gov-local"};
      const fields = {tenant_domain: "example.eu", global_password_prefix: "hunter2", nos_data_root: "/Volumes/SSD1TB/nos",
                      instance_name: DATA.defaults.instance_name, restic_repo: "", configure_external_storage: true};
      const on = mergeFlags(DATA, picks, "mailpit", {install_kiwix: true, install_backrest: true});
      console.log(JSON.stringify({yaml: renderConfig(DATA, fields, picks, "mailpit", on), on, local: isLocalDomain(DATA, "example.eu")}));
    ''')
    cfg = yaml.safe_load(res["yaml"])
    assert cfg["tenant_domain"] == "example.eu" and cfg["nos_data_root"] == "/Volumes/SSD1TB/nos"
    assert cfg["configure_external_storage"] is True
    assert "instance_name" not in cfg and "restic_repo" not in cfg, "a field equal to its default, or empty, is noise"
    assert "global_password_prefix" not in res["yaml"] and "hunter2" not in res["yaml"]
    assert cfg["enforce_mfa"] is True, "gov-local's knobs did not land"
    assert cfg["install_backrest"] is True, "a step's install_* switch lands under # services"
    defaults = {f["key"]: f["default"] for f in pb.build()["flags"]}
    assert all(cfg[k] != defaults[k] for k in cfg if k.startswith("install_")), "a line that equals the default is noise"
    assert res["local"] is False


@needs_node
def test_the_estimate_is_measured_memory_plus_one_assumption_table():
    heavy = re.search(r'^docker_mem_limit_heavy:\s*"(\d+)g"', CONFIG_TEXT, re.M).group(1)
    gitlab_tpl = (REPO / "roles/pazny.gitlab/templates/compose.yml.j2").read_text()
    assert "docker_mem_limit_heavy" in gitlab_tpl, "the fact this test leans on moved"
    res = _node('''
      const base = mergeFlags(DATA, {"service-set": "dev-minimal"}, "none", {install_gitlab: false});
      const withGl = {...base, install_gitlab: true};
      const k = knobs(DATA, {"service-set": "dev-minimal"}, {});
      const a = estimate(DATA, base, k), b = estimate(DATA, withGl, k);
      console.log(JSON.stringify({delta: b.mem_bytes - a.mem_bytes, img: a.image_bytes, data_gb: a.data_gb,
        wing_host: DATA.services.install_wing.host, wing_mem: DATA.services.install_wing.mem_bytes,
        enabled: a.rows.map(r => r.ids).flat()}));
    ''')
    assert res["delta"] == int(heavy) << 30, "turning gitlab on must add exactly its declared mem_limit"
    assert res["wing_host"] is True and res["wing_mem"] == 0, "a host daemon has no container limit and says so"
    assert res["img"] is None, "without a lock the image size is unknown, never 0"
    rows = {r["id"]: r for r in yaml.safe_load((REPO / "state/manifest.yml").read_text())["services"]}
    expect = sum(pb.DATA_GB_ASSUMED.get(rows[i].get("category"), pb.DATA_GB_ASSUMED["_default"])
                 for i in res["enabled"] if i in rows)
    expect += sum(pb.DATA_GB_ASSUMED["app"] for i in res["enabled"] if i.startswith("app:"))
    assert res["data_gb"] == expect, "the data figure must be the assumption table applied per manifest category"


@needs_node
def test_an_offline_build_switches_off_what_its_lock_lacks(tmp_path):
    online = pb.build()
    gitlab = online["services"]["install_gitlab"]["images"]
    lock = {"version": 1, "images": {}}
    for s in online["services"].values():
        for img in s["images"]:
            if img not in gitlab and img.split("/", 1)[0] not in pb.reach.LOCAL_NAMESPACES:
                lock["images"][img.removeprefix("docker.io/")] = {"bytes": 1 << 20, "id": "sha256:x", "digests": []}
    lock_path = tmp_path / "images.lock.json"
    lock_path.write_text(json.dumps(lock))
    offline = pb.build(lock_path)
    assert offline["offline"] and not online["offline"]
    assert offline["services"]["install_gitlab"]["missing"] == gitlab
    assert offline["services"]["install_postgresql"]["offline_ok"]
    res = _node('''
      const on = mergeFlags(DATA, {"service-set": "all-on"}, "none", {install_gitlab: true});
      const e = estimate(DATA, on, knobs(DATA, {"service-set": "all-on"}, {}));
      console.log(JSON.stringify({gitlab: on.install_gitlab, why: blocked(DATA, "install_gitlab"), pg: on.install_postgresql,
        img: e.image_bytes, pulled: e.rows.filter(r => !r.host).length}));
    ''', offline)
    assert res["gitlab"] is False and "not in this offline build" in res["why"], "all-on turns gitlab on; the lock must win"
    assert res["pg"] is True and not _node('console.log(JSON.stringify(blocked(DATA, "install_gitlab")))', online)
    assert res["img"] > 0, "image bytes come from the lock"
    # the built page carries the offline data and its UI script parses
    out = tmp_path / "site"
    subprocess.run(["python3", str(REPO / "tools/profile-builder-build.py"), "--out", str(out),
                    "--image-lock", str(lock_path)], check=True, capture_output=True)
    html = (out / "index.html").read_text()
    assert '"offline": true' in html or '"offline":true' in html
    ui = tmp_path / "ui.js"
    ui.write_text(re.search(r"<script>\n(const DATA.*?)</script>", html, re.S).group(1))
    subprocess.run([NODE, "--check", str(ui)], check=True)
