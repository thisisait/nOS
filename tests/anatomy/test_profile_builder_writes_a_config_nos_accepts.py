"""The profile builder is a static page whose every fact comes from the
artifacts at build time, and whose JS merge is RUN here under node — a page
that lists services from prose would drift the day a flag is added.

  1. the data derives every install_* flag default.config.yml declares and
     every profile that carries an `axis:` header;
  2. the merge (default → service-set → use-case → policy → environment →
     constraint → mail) reproduces a profile's own flags when it is picked;
  3. the config.yml it writes parses as YAML, holds only overrides, and never
     the password prefix.
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
_spec = importlib.util.spec_from_file_location("pb", REPO / "tools/profile-builder-build.py")
pb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pb)
NODE = shutil.which("node")


def test_the_data_is_the_artifacts_not_a_list():
    data = pb.build()
    declared = set(re.findall(r"^(install_[a-z0-9_]+):", (REPO / "default.config.yml").read_text(), re.M))
    assert {f["key"] for f in data["flags"]} == declared
    axes_on_disk = {p.stem for p in (REPO / "profiles").glob("*.yml")
                    if re.search(r"^# axis: ", p.read_text(), re.M)}
    assert {p["id"] for p in data["profiles"]} == axes_on_disk
    assert all(p["axis"] in data["axes"] for p in data["profiles"]), "a profile declares an axis the page has no step for"
    assert all(f["section"] for f in data["flags"])


def _node(script: str) -> dict:
    tpl = (REPO / "tools/profile-builder/index.html.tpl").read_text()
    logic = re.search(r'<script id="logic">(.*?)</script>', tpl, re.S).group(1)
    data = json.dumps(pb.build())
    out = subprocess.run([NODE, "-e", logic + f"\nconst DATA={data};\n" + script],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@pytest.mark.skipif(not NODE, reason="node is how the page's own merge is executed")
def test_picking_a_profile_reproduces_its_flags():
    res = _node('''
      const on = mergeFlags(DATA, {"service-set": "dev-minimal"}, "none");
      const prof = DATA.profiles.find(p => p.id === "dev-minimal");
      const bad = Object.entries(prof.flags).filter(([k, v]) => on[k] !== v);
      const layered = mergeFlags(DATA, {"service-set": "dev-minimal", "use-case": "praxis"}, "stalwart");
      console.log(JSON.stringify({bad, stalwart: layered.install_smtp_stalwart, mailpit: layered.install_mailpit,
        praxis_wins: Object.entries(DATA.profiles.find(p => p.id === "praxis").flags).every(([k, v]) => layered[k] === v)}));
    ''')
    assert res["bad"] == [], f"picking dev-minimal did not reproduce it: {res['bad']}"
    assert res["stalwart"] is True and res["mailpit"] is False, "the mail choice must be the last word"
    assert res["praxis_wins"], "use-case must layer over service-set"


@pytest.mark.skipif(not NODE, reason="node is how the page's own merge is executed")
def test_the_written_config_is_yaml_overrides_only_and_no_secret():
    res = _node('''
      const picks = {"service-set": "dev-minimal", "policy": "gov-local"};
      const params = {...DATA.param_defaults, tenant_domain: "example.eu", global_password_prefix: "hunter2"};
      const on = mergeFlags(DATA, picks, "mailpit");
      on.install_kiwix = !on.install_kiwix;   // one manual toggle in step 3
      console.log(JSON.stringify({yaml: renderConfig(DATA, params, picks, "mailpit", on), kiwix: on.install_kiwix}));
    ''')
    cfg = yaml.safe_load(res["yaml"])
    assert cfg["tenant_domain"] == "example.eu"
    assert "global_password_prefix" not in res["yaml"] and "hunter2" not in res["yaml"]
    assert cfg["enforce_mfa"] is True, "gov-local's knobs did not land"
    defaults = {f["key"]: f["default"] for f in pb.build()["flags"]}
    # the toggle is written only when it differs from the default — overrides, not a dump
    assert cfg.get("install_kiwix", defaults["install_kiwix"]) == res["kiwix"]
    assert all(cfg[k] != defaults[k] for k in cfg if k.startswith("install_")), "a line that equals the default is noise"
