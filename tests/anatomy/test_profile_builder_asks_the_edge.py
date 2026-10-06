"""The profile builder asks how clients reach the host and who hosts the DNS, and
writes only what nOS accepts.

  1. nos_edge is a choice of exactly the values main.yml's preflight accepts; left
     on "decide", it is the playbook's own default rendered for the domain class;
  2. acme_dns_provider is a page field, so the extractor must carry the ACME
     refusals' `acme_dns_provider == 'dns_cf'` as a TEXT literal, not stop;
  3. a Wedos (or any non-Cloudflare) domain needs acme.sh's own credential names
     in credentials.yml (acme_dns_env), and no Cloudflare token;
  4. the provider table names the env keys acme.sh's dnsapi/<id>.sh declares.
Operator decisions 2026-10-06 (Shape A, A2 at Wedos), roadmap row edge-builder-questions.
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
rules = pb.rules
needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node is how the page's own logic is executed")
PREFIX = "FAKEprefix12345678"
WEDOS = {"WEDOS_Username": "it@firma.cz", "WEDOS_Wapipass": "fake-wapi"}


@pytest.fixture(scope="module")
def data() -> dict:
    return pb.build()


def _field(data, key):
    return next(f for s in data["steps"] for f in s["fields"] if f["key"] == key)


def test_the_edge_choices_are_what_the_preflight_accepts(data):
    main = (REPO / "main.yml").read_text()
    accepted = re.search(r"nos_edge \| default\('cloudflare'\) not in (\[[^\]]*\])", main).group(1)
    edge = _field(data, "nos_edge")
    assert sorted(o["value"] for o in edge["options"] if o["value"]) == sorted(yaml.safe_load(accepted))
    assert data["derived_values"]["nos_edge"] == {"local": "lan_tailscale", "public": "cloudflare"}


def test_the_extractor_carries_text_literals(data):
    assert rules.literal("(nos_edge | default('cloudflare')) == 'lan_tailscale'") == ("nos_edge", "==lan_tailscale")
    assert rules.literal("not ((nos_edge | default('cloudflare')) == 'lan_tailscale')") == ("nos_edge", "!=lan_tailscale")
    assert rules.literal("acme_dns_provider | default('dns_cf') != 'dns_cf'") == ("acme_dns_provider", "!=dns_cf")
    lits = {r["source"].split(": ", 1)[1]: r["all"] for r in data["rules"] if r["cls"] == "refused" and "ACME" in r["source"]}
    assert ["acme_dns_provider", "==dns_cf"] in lits["[ACME] Refuse to run without a Cloudflare API token"]
    assert ["acme_dns_provider", "!=dns_cf"] in lits["[ACME] Refuse a DNS provider with no credentials"]
    assert ["acme_dns_env", False] in lits["[ACME] Refuse a DNS provider with no credentials"]


def _node(script: str, data: dict, logic: str | None = None):
    out = subprocess.run(["node", "-e", (logic or rules.logic_js()) + f"\nconst DATA={json.dumps(data)};\n" + script],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


CASES = {
    "wedos_no_login": {"acme_dns_provider": "dns_wedos"},
    "wedos_half": {"acme_dns_provider": "dns_wedos", "acme_dns_env": {"WEDOS_Username": "it@firma.cz"}},
    "wedos": {"acme_dns_provider": "dns_wedos", "acme_dns_env": WEDOS, "nos_edge": "lan_tailscale"},
    "cloudflare_no_token": {},
    "bad_edge": {"nos_edge": "cloudfare", "acme_cloudflare_api_token": "cf"},
    "other_id": {"acme_dns_provider": "dns_acmeproxy", "acme_dns_env": {"ACMEPROXY_ENDPOINT": "https://p", "ACMEPROXY_USERNAME": "u", "ACMEPROXY_PASSWORD": "p"}},
}


def _judge(data, logic=None) -> dict:
    states = {k: {"fields": {"global_password_prefix": PREFIX, "tenant_domain": "firma.cz", **v},
                  "picks": {}, "mail": None, "manual": {}, "people": []} for k, v in CASES.items()}
    return _node(f"const C = {json.dumps(states)};\n" + r"""
      const out = {};
      for (const [k, s] of Object.entries(C)) {
        const on = settle(DATA, s).on;
        out[k] = {problems: problems(DATA, s).map(p => [p.key, p.msg]), config: renderConfig(DATA, s, on),
                  creds: renderCredentials(DATA, s.fields.global_password_prefix, s.fields)};
      }
      console.log(JSON.stringify(out));""", data, logic)


@needs_node
def test_a_wedos_domain_writes_a_config_nos_accepts(data):
    res, judge = _judge(data), rules.Oracle(data)
    keys = {k: [p[0] for p in v["problems"]] for k, v in res.items()}
    assert keys["wedos"] == [] and keys["other_id"] == [], {k: res[k]["problems"] for k in ("wedos", "other_id")}
    cfg, creds = yaml.safe_load(res["wedos"]["config"]), yaml.safe_load(res["wedos"]["creds"])
    assert cfg["acme_dns_provider"] == "dns_wedos" and cfg["nos_edge"] == "lan_tailscale"
    assert creds["acme_dns_env"] == WEDOS and "acme_cloudflare_api_token" not in creds
    assert "WEDOS" not in res["wedos"]["config"], "a credential never lands in config.yml"
    assert judge(cfg, creds) == [], "the page's config is refused by the playbook's own expressions"
    assert judge(cfg, {k: v for k, v in creds.items() if k != "acme_dns_env"}), "positive control: no login is refused"


@needs_node
def test_the_page_refuses_what_nos_refuses(data):
    res = _judge(data)
    msgs = {k: " ".join(m for _, m in v["problems"]) for k, v in res.items()}
    assert "no DNS host API login is given" in msgs["wedos_no_login"] and "Cloudflare" not in msgs["wedos_no_login"]
    assert msgs["wedos_half"] == "Fill in WEDOS_Wapipass."
    assert "no Cloudflare API token is given" in msgs["cloudflare_no_token"]
    assert [k for k, _ in res["bad_edge"]["problems"]] == ["nos_edge"]


@needs_node
def test_the_gate_goes_red_without_text_literals(data):
    """Red control: a page comparing "==dns_cf" as a boolean asks a Wedos firm for a Cloudflare token."""
    old = "r.all.every(holds)"
    assert old in rules.logic_js()
    res = _judge(data, rules.logic_js().replace(old, "r.all.every(([v, want]) => typeof want === 'string' ? false : holds([v, want]))"))
    assert [p for p in res["wedos_no_login"]["problems"] if p[0] == "acme_dns_env"] == [], "the broken page lets it through"
    assert _judge(data)["wedos_no_login"]["problems"], "and the real page does not"


ACMESH = [Path("/opt/homebrew/opt/acme.sh/libexec/dnsapi"), Path("/usr/local/opt/acme.sh/libexec/dnsapi"), Path.home() / ".acme.sh/dnsapi"]


def test_the_provider_table_is_acme_shs_own_names(data):
    ids = [p["id"] for p in data["dns_providers"]]
    assert ids[0] == "dns_cf" and {"dns_wedos", "dns_hetznercloud", "dns_desec", "dns_ovh"} <= set(ids)
    assert pb.rules._cfg()["acme_dns_provider"] == "dns_cf", "the default stays Cloudflare"
    api = next((d for d in ACMESH if d.is_dir()), None)
    if api is None:
        pytest.skip("acme.sh is not installed here: the env names cannot be re-read")
    for p in data["dns_providers"][1:]:
        text = (api / f"{p['id']}.sh").read_text()
        declared = re.findall(r"^ ([A-Za-z_][A-Za-z0-9_]*) ", text.split("Options:", 1)[1].split("Issues:", 1)[0], re.M)
        assert set(p["env"]) <= set(declared), f"{p['id']}: {p['env']} vs acme.sh {declared}"
