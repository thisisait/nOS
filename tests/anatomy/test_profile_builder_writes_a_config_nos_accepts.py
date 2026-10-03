"""The profile builder is a static page whose every fact comes from the
artifacts at build time, and whose JS is RUN here under node — a page that
lists services from prose would drift the day a flag is added.

  1. the data derives every install_* flag default.config.yml declares, every
     profile that carries an `axis:` header, and every step field is a variable
     the config declares; groups come from the manifest's closed category enum;
  2. the merge (default → service-set → use-case → policy → environment →
     constraint → mail → your toggles) reproduces a profile's own flags, an
     untouched mail choice overrides nothing, and your answer outranks a knob;
  3. the config.yml it writes parses as YAML, holds only overrides, each key
     once, and never the password prefix (that goes to credentials.yml alone);
  4. the RAM estimate is the sum of the compose templates' rendered mem_limit,
     the data figure is the one assumption table applied per manifest category;
  5. built with an image lock, a service whose image the lock lacks is OFF and
     says why — resolved against the operator's config.yml when one is given;
  6. one timezone, asked once; a nearest-profile suggestion that a contradiction
     silences; problems() refuses what the playbook would refuse.
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
PREFIX = "FAKEprefix12345678"


def test_the_data_is_the_artifacts_not_a_list():
    data = pb.build()
    declared = set(re.findall(r"^(install_[a-z0-9_]+):", CONFIG_TEXT, re.M))
    assert {f["key"] for f in data["flags"]} == declared
    axes_on_disk = {p.stem for p in (REPO / "profiles").glob("*.yml")
                    if re.search(r"^# axis: ", p.read_text(), re.M)}
    assert {p["id"] for p in data["profiles"]} == axes_on_disk
    assert all(p["axis"] in data["axes"] and p["axis"] in data["axis_questions"] for p in data["profiles"])
    every_var = set(re.findall(r"^([a-z_]+):", CONFIG_TEXT, re.M))
    secrets = set(re.findall(r"^([a-z_]+):", (REPO / "default.credentials.yml").read_text(), re.M))
    for step in data["steps"]:
        for f in step["fields"]:
            assert f["key"] in (every_var | secrets if f.get("secret") else every_var), \
                f"step field {f['key']} is not a variable default.config.yml (a secret: default.credentials.yml) declares"
            assert f["hint"], f"{f['key']} has no plain-language line"
            assert f.get("when") in (None, *every_var), f"{f['key']}: `when` names no declared variable"
    assert [s["id"] for s in data["steps"]] == ["machine", "domain", "owner", "services", "backup", "accounts", "review"]
    offered = [p for p in data["profiles"] if not p["step"]]
    assert all(p["plain"] for p in offered), "a profile offered to a person needs a `# plain:` line"


def test_groups_come_from_the_manifest_category_enum():
    enum = json.loads((REPO / "state/schema/manifest.schema.json").read_text())["definitions"]["service"]["properties"]["category"]["enum"]
    placed = [c for _, cs in pb.GROUPS for c in cs]
    assert sorted(placed) == sorted(set(placed)), "a category sits in two groups"
    assert set(enum) == set(placed), f"categories without a plain group: {set(enum) - set(placed)}; stale: {set(placed) - set(enum)}"
    data = pb.build()
    rows = {r["install_flag"] for r in yaml.safe_load((REPO / "state/manifest.yml").read_text())["services"] if r.get("install_flag")}
    for f in data["flags"]:
        assert f["group"] in data["groups"] and f["title"]
        assert (f["group"] == pb.HOST_GROUP) == (f["key"] not in rows), f["key"]
    nc = next(f for f in data["flags"] if f["key"] == "install_nextcloud")
    assert nc["title"] == "Nextcloud" and "files" in nc["plain"], "the plain name is the plugin's hub_card"


def test_one_timezone_every_service_derives_from_it():
    cfg = yaml.safe_load(CONFIG_TEXT)
    assert cfg["nos_timezone"] == "Europe/Prague"
    tz_keys = [k for k in cfg if re.search(r"_(timezone|tz)$", k) and k != "nos_timezone"]
    assert len(tz_keys) >= 7 and all(cfg[k] == "{{ nos_timezone }}" for k in tz_keys), tz_keys
    literal = []
    for p in list(REPO.glob("roles/*/defaults/main.yml")) + list(REPO.glob("roles/*/templates/*.j2")):
        for ln in p.read_text().splitlines():
            bare = re.sub(r"""default\(['"]Europe/Prague['"]\)""", "", ln)   # a fallback of a derived var is fine
            if "Europe/Prague" in bare and not ln.lstrip().startswith("#"):
                literal.append(f"{p.relative_to(REPO)}: {ln.strip()}")
    assert not literal, "a timezone that ignores nos_timezone:\n  " + "\n  ".join(literal)
    machine = pb.build()["steps"][0]
    assert machine["fields"][0]["key"] == "nos_timezone", "asked once, first"


def _node(script: str, data: dict | None = None) -> dict:
    tpl = (REPO / "tools/profile-builder/index.html.tpl").read_text()
    logic = re.search(r'<script id="logic">(.*?)</script>', tpl, re.S).group(1)
    out = subprocess.run([NODE, "-e", logic + f"\nconst DATA={json.dumps(data or pb.build())};\n" + script],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@needs_node
def test_picking_a_profile_reproduces_its_flags():
    res = _node('''
      const on = mergeFlags(DATA, {"service-set": "dev-minimal"}, null, {});
      const prof = DATA.profiles.find(p => p.id === "dev-minimal");
      const bad = Object.entries(prof.flags).filter(([k, v]) => on[k] !== v);
      const layered = mergeFlags(DATA, {"service-set": "dev-minimal", "use-case": "praxis"}, "stalwart", {install_kiwix: !prof.flags.install_kiwix});
      console.log(JSON.stringify({bad, stalwart: layered.install_smtp_stalwart, mailpit: layered.install_mailpit,
        manual_wins: layered.install_kiwix === !prof.flags.install_kiwix, shown_mail: mailOf(DATA, on),
        praxis_wins: Object.entries(DATA.profiles.find(p => p.id === "praxis").flags).every(([k, v]) => layered[k] === v)}));
    ''')
    assert res["bad"] == [], f"picking dev-minimal did not reproduce it: {res['bad']}"
    assert res["shown_mail"] == "none", "an untouched mail choice must not undo dev-minimal's install_mailpit: false"
    assert res["stalwart"] is True and res["mailpit"] is False, "a mail choice the person made must outrank the profiles"
    assert res["praxis_wins"], "use-case must layer over service-set"
    assert res["manual_wins"], "a toggle the person made must be the last word"


def _state(**kw) -> str:
    s = {"fields": {"global_password_prefix": PREFIX}, "picks": {}, "mail": None, "manual": {}, "people": []}
    for k, v in kw.items():
        s[k] = {**s[k], **v} if isinstance(v, dict) and k == "fields" else v
    return json.dumps(s)


@needs_node
def test_the_written_config_is_yaml_overrides_only_and_no_secret():
    s = _state(picks={"service-set": "dev-minimal", "policy": "gov-local"},
               fields={"tenant_domain": "example.eu", "nos_data_root": "/Volumes/SSD1TB/nos", "nos_timezone": "Europe/London",
                       "instance_name": pb.build()["defaults"]["instance_name"], "restic_repo": "",
                       "configure_external_storage": True, "enforce_mfa": False},
               manual={"install_kiwix": True, "install_backrest": True})
    res = _node(f'''
      const s = {s};
      const on = mergeFlags(DATA, s.picks, s.mail, s.manual);
      console.log(JSON.stringify({{yaml: renderConfig(DATA, s, on), creds: renderCredentials(DATA, s.fields.global_password_prefix),
        shown: fieldValue(DATA, s.picks, {{}}, "enforce_mfa"), local: isLocalDomain(DATA, "example.eu")}}));
    ''')
    cfg = yaml.safe_load(res["yaml"])
    keys = re.findall(r"^([a-z_]+):", res["yaml"], re.M)
    assert len(keys) == len(set(keys)), "a key written twice — Ansible keeps the last, silently"
    assert cfg["tenant_domain"] == "example.eu" and cfg["nos_data_root"] == "/Volumes/SSD1TB/nos"
    assert cfg["nos_timezone"] == "Europe/London" and cfg["configure_external_storage"] is True
    assert "instance_name" not in cfg and "restic_repo" not in cfg, "a field equal to its default, or empty, is noise"
    assert PREFIX not in res["yaml"] and "global_password_prefix" not in res["yaml"]
    assert yaml.safe_load(res["creds"]) == {"global_password_prefix": PREFIX}, "the prefix goes to credentials.yml"
    assert "enforce_mfa" not in cfg, "your 'off' outranks gov-local's knob, and equals the default"
    assert res["shown"] is True, "an untouched field shows the picked profile's value"
    assert cfg["wing_audit_chain_enabled"] is True, "gov-local's other knobs still land"
    assert cfg["install_backrest"] is True, "a step's install_* switch lands under # services"
    defaults = {f["key"]: f["default"] for f in pb.build()["flags"]}
    assert all(cfg[k] != defaults[k] for k in cfg if k.startswith("install_")), "a line that equals the default is noise"
    assert res["local"] is False


@needs_node
def test_problems_refuse_what_nos_would_refuse():
    main = (REPO / "main.yml").read_text()
    weak = re.search(r"Refuse a weak password prefix.*?that:(.*?)fail_msg", main, re.S).group(1)
    assert f">= {pb.PREFIX_RULE['min']}" in weak and "['changeme', '']" in weak, "the page's prefix rule left main.yml's"
    cases = {
        "ok": _state(fields={"nos_data_root": "/Volumes/SSD/nos"}),
        "no_prefix": _state(fields={"global_password_prefix": ""}),
        "changeme": _state(fields={"global_password_prefix": "changeme"}),
        "tilde": _state(fields={"nos_data_root": "~/nos"}),
        "tz": _state(fields={"nos_timezone": "Prague"}),
        "repo": _state(manual={"install_backrest": True}),
        "same_mail": _state(fields={"nos_operator_email": "admin@dev.local"}),
    }
    res = _node("const C = {" + ",".join(f'"{k}": {v}' for k, v in cases.items()) + "};\n"
                "console.log(JSON.stringify(Object.fromEntries(Object.entries(C).map(([k, s]) => [k, problems(DATA, s).map(p => p.key)]))));")
    assert res["ok"] == [], res["ok"]
    assert res["no_prefix"] == res["changeme"] == ["global_password_prefix"]
    assert res["tilde"] == ["nos_data_root"] and res["tz"] == ["nos_timezone"]
    assert res["repo"] == ["restic_repo"] and res["same_mail"] == ["nos_operator_email"]


@needs_node
def test_nearest_profile_follows_answers_and_a_contradiction_silences_it():
    res = _node('''
      const s = {fields: {enforce_mfa: true}, picks: {}, manual: {}, mail: null};
      const clash = {fields: {enforce_mfa: true, backup_encryption_enabled: false}, picks: {}, manual: {}, mail: null};
      console.log(JSON.stringify({hit: nearest(DATA, s), clash: nearest(DATA, clash), picked: nearest(DATA, {...s, picks: {policy: "gov-local"}}),
        none: nearest(DATA, {fields: {}, picks: {}, manual: {}, mail: null})}));
    ''')
    assert {"axis": "policy", "id": "gov-local", "agree": ["enforce_mfa"]} in res["hit"]
    assert not any(x["id"] == "gov-local" for x in res["clash"]), "gov-local encrypts backups; you turned that off"
    assert not any(x["id"] == "gov-local" for x in res["picked"]), "a picked profile is not suggested again"
    assert res["none"] == [], "no answers, no suggestion"


@needs_node
def test_test_users_are_the_people_step_not_an_axis_choice():
    data = pb.build()
    tu = next(p for p in data["profiles"] if p["id"] == "test-users")
    assert tu["step"] == "accounts" and tu["knobs"] == {"nos_test_users_enabled": True}
    assert "nos_test_users_enabled" in {f["key"] for f in data["steps"][5]["fields"]}
    assert [u["name"] for u in data["accounts"]["test_users"]] == ["alice", "bob", "carol", "dave"]
    assert [t["label"] for t in data["accounts"]["tiers"]] == ["admin", "manager", "user", "guest"]
    res = _node(f'''
      const s = {_state(fields={"nos_test_users_enabled": True})};
      console.log(JSON.stringify(renderConfig(DATA, s, mergeFlags(DATA, s.picks, s.mail, s.manual))));
    ''')
    assert yaml.safe_load(res)["nos_test_users_enabled"] is True


@needs_node
def test_the_estimate_is_measured_memory_plus_one_assumption_table():
    heavy = re.search(r'^docker_mem_limit_heavy:\s*"(\d+)g"', CONFIG_TEXT, re.M).group(1)
    gitlab_tpl = (REPO / "roles/pazny.gitlab/templates/compose.yml.j2").read_text()
    assert "docker_mem_limit_heavy" in gitlab_tpl, "the fact this test leans on moved"
    res = _node('''
      const base = mergeFlags(DATA, {"service-set": "dev-minimal"}, null, {install_gitlab: false});
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


def test_no_service_lists_an_image_twice():
    svcs = pb.build()["services"]
    dup = {k: s["images"] for k, s in svcs.items() if len(s["images"]) != len(set(s["images"]))}
    assert not dup, dup
    assert len(svcs["install_erpnext"]["images"]) == 1, "ERPNext's six containers share one image"


def _lock(tmp_path, images, size=1 << 20):
    lock = {"version": 1, "images": {i.removeprefix("docker.io/"): {"bytes": size, "id": "sha256:x", "digests": []} for i in images}}
    p = tmp_path / "images.lock.json"
    p.write_text(json.dumps(lock))
    return p


@needs_node
def test_an_offline_build_switches_off_what_its_lock_lacks(tmp_path):
    online = pb.build()
    gitlab = online["services"]["install_gitlab"]["images"]
    pulled = {i for s in online["services"].values() for i in s["images"]
              if i not in gitlab and i.split("/", 1)[0] not in pb.reach.LOCAL_NAMESPACES}
    lock_path = _lock(tmp_path, pulled)
    offline = pb.build(lock_path)
    shared = offline["services"]["install_postgresql"]["image_sizes"]       # make two services share one image
    offline["services"]["install_mariadb"]["image_sizes"].update(shared)
    offline["services"]["install_mariadb"]["image_bytes"] += sum(shared.values())
    assert offline["offline"] and not online["offline"]
    assert offline["services"]["install_gitlab"]["missing"] == gitlab
    assert offline["services"]["install_postgresql"]["offline_ok"]
    res = _node('''
      const on = mergeFlags(DATA, {"service-set": "all-on"}, null, {install_gitlab: true});
      const e = estimate(DATA, on, knobs(DATA, {"service-set": "all-on"}, {}));
      const perService = e.rows.reduce((n, r) => n + (r.image_bytes || 0), 0);
      console.log(JSON.stringify({gitlab: on.install_gitlab, why: blocked(DATA, "install_gitlab"), pg: on.install_postgresql,
        img: e.image_bytes, perService}));
    ''', offline)
    assert res["gitlab"] is False and "not in this offline build" in res["why"], "all-on turns gitlab on; the lock must win"
    assert res["pg"] is True and not _node('console.log(JSON.stringify(blocked(DATA, "install_gitlab")))', online)
    assert 0 < res["img"] < res["perService"], "an image two services share is stored once, counted once"


def test_an_operator_image_override_is_what_the_offline_list_looks_up(tmp_path):
    swap = "ghcr.io/euro-office/documentserver"
    online = pb.build()
    stock = online["services"]["install_onlyoffice"]["images"]
    assert stock and not stock[0].startswith(swap)
    tag = stock[0].rsplit(":", 1)[1]
    lock_path = _lock(tmp_path, [f"{swap}:{tag}"])
    cfg = tmp_path / "config.yml"
    cfg.write_text(f'onlyoffice_image: "{swap}"\n')
    assert not pb.build(lock_path)["services"]["install_onlyoffice"]["offline_ok"], "positive control: stock image is missing"
    assert pb.build(lock_path, cfg)["services"]["install_onlyoffice"]["offline_ok"], "the override is the image the converge pulls"


def test_the_built_page_is_one_file_that_works_from_disk(tmp_path):
    out = tmp_path / "site"
    subprocess.run(["python3", str(REPO / "tools/profile-builder-build.py"), "--out", str(out)], check=True, capture_output=True)
    html = (out / "index.html").read_text()
    assert "__DATA__" not in html
    assert not re.search(r'<(script|link|img)[^>]+(src|href)=', html), "a file:// page cannot rely on a second file"
    assert "fetch(" not in html and "XMLHttpRequest" not in html, "nothing is fetched — answers stay on the page"
    if NODE:
        ui = tmp_path / "ui.js"
        ui.write_text(re.search(r"<script>\n(const DATA.*?)</script>", html, re.S).group(1))
        subprocess.run([NODE, "--check", str(ui)], check=True)
