"""MikoPBX: one login path, and the media settings a phone actually needs.

Measured 2026-10-03 on a throwaway mikopbx/mikopbx:2026.3.40 behind Docker
Desktop (macOS): SIP REGISTER over the published UDP port answered 200, but
the INVITE's SDP carried the CONTAINER address (c=172.17.0.3) — no audio —
because every published packet arrives from the bridge gateway, which sits in
Asterisk's local_net. Audio came back only after three things landed through
MikoPBX's own API: NAT on with the host address, auto-external-IP off (the env
path forces it ON and the public IP then overwrites the setting every boot),
and a custom-files script dropping `local_net=` on macOS. Env vars are read on
FIRST boot only, so none of this may live in compose alone.

Pinned here, offline:
  1. the SSO claim is one claim: plugin forward_auth == fragment proxy ==
     manifest `oidc: proxy`; no native_oidc wiring anywhere (the honest ceiling
     — MikoPBX core has no OIDC/SAML/header auth; see docs/systems/mikopbx).
  2. the compose fragment publishes SIP udp+tcp AND the whole RTP range on the
     same ports Asterisk is told to use (RTP_PORT_FROM/TO) — a range published
     on different numbers than Asterisk binds is the classic one-way-audio.
  3. post.yml re-asserts NAT + RTP through REST, drops local_net ONLY on
     Darwin, and ends in a reader on what Asterisk LOADED, not on the API echo.
"""
from __future__ import annotations

import sys
import re
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402
ROLE = REPO / "roles/pazny.mikopbx"
PLUGIN = REPO / "files/anatomy/plugins/mikopbx-base"


def _manifest_row():
    doc = yaml.safe_load((REPO / "state/manifest.yml").read_text())
    return next(s for s in doc["services"] if s["id"] == "mikopbx")


def test_one_sso_claim_forward_auth_everywhere():
    plugin = yaml.safe_load((PLUGIN / "plugin.yml").read_text())
    frag = yaml.safe_load((PLUGIN / "manifest.fragment.yml").read_text())
    assert plugin["authentik"]["mode"] == "forward_auth"
    assert frag["auth"] == "proxy" and frag["authentik"]["mode"] == "forward_auth"
    assert _manifest_row()["oidc"] == "proxy"
    assert "redirect_uris" not in plugin["authentik"], "forward_auth has no OIDC callback"
    text = (ROLE / "tasks/post.yml").read_text() + (ROLE / "templates/compose.yml.j2").read_text()
    assert "oidc" not in text.lower(), "no native OIDC wiring may hide in the role"


def _render(**overrides):
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["bool"] = lambda v: str(v).lower() in ("true", "1", "yes")
    ctx = dict(mikopbx_version="2026.3.40", mikopbx_port=8088, mikopbx_sip_port=5060,
               mikopbx_rtp_start=10000, mikopbx_rtp_end=10100, mikopbx_lan_access=False,
               mikopbx_data_dir="/data/mikopbx", mikopbx_pbx_name="nOS PBX", mikopbx_admin_login="admin",
               mikopbx_admin_password="x", mikopbx_timezone="Europe/Prague", stacks_shared_network="shared_net",
               docker_mem_limit_standard="1g", docker_cpus_standard="1.0", mikopbx_mem_limit="1g", mikopbx_cpus="1.0")
    ctx.update(overrides)
    return yaml.safe_load(env.from_string((ROLE / "templates/compose.yml.j2").read_text()).render(**ctx))


def test_published_sip_and_rtp_match_what_asterisk_binds():
    for lan in (False, True):
        svc = _render(mikopbx_lan_access=lan, mikopbx_rtp_start=20000, mikopbx_rtp_end=20050, mikopbx_sip_port=5070)
        svc = svc["services"]["mikopbx"]
        ports = svc["ports"]
        bind = "" if lan else "127.0.0.1:"
        assert f"{bind}5070:5060/udp" in ports and f"{bind}5070:5060/tcp" in ports
        assert f"{bind}20000-20050:20000-20050/udp" in ports, ports
        env = svc["environment"]
        assert (env["RTP_PORT_FROM"], env["RTP_PORT_TO"], env["EXTERNAL_SIP_PORT"]) == ("20000", "20050", "5070")
        assert env["ENABLE_USE_NAT"] == "1"
        assert "system:ping" in svc["healthcheck"]["test"][-1]


def test_post_reasserts_media_settings_and_reads_what_asterisk_loaded():
    post = yaml.safe_load((ROLE / "tasks/post.yml").read_text())
    by_name = {t["name"]: t for t in post}
    nat = next(t for t in post if "network:saveConfig" in str(t.get("ansible.builtin.uri", {}).get("url")))
    assert nat["ansible.builtin.uri"]["body"]["usenat"] is True
    gs = next(t for t in post if t.get("ansible.builtin.uri", {}).get("method") == "PATCH"
              and "general-settings" in t["ansible.builtin.uri"]["url"])
    assert gs["ansible.builtin.uri"]["body"]["autoUpdateExternalIp"] is False
    mac = next(t for t in post if "local_net" in t["name"])
    assert "_pbx_is_mac" in str(mac["when"]), "the local_net drop is a Docker Desktop fact, not a global"
    assert "Darwin" in str(by_name["[pazny.mikopbx Post] Set API facts"]["ansible.builtin.set_fact"]["_pbx_is_mac"])
    script = (ROLE / "files/pjsip-no-local-net.sh").read_text()
    assert re.search(r"sed .*local_net=", script)
    # success is read from the loaded asterisk config, after an optional restart
    names = [t["name"] for t in post]
    loaded = names.index("[pazny.mikopbx Post] What Asterisk actually loaded")
    restart = names.index("[pazny.mikopbx Post] Restart once if the loaded config is stale")
    final = names.index("[pazny.mikopbx Post] Asterisk must run the declared media config (no silent green)")
    assert loaded < restart < final == len(names) - 1
    assert "external_media_address" in str(post[final]["ansible.builtin.assert"]["that"])


def test_default_off_and_pinned():
    cfg = ni.default_config()
    assert cfg["install_mikopbx"] is False
    assert re.fullmatch(r"\d{4}\.\d+\.\d+", str(cfg["mikopbx_version"]))
    assert _manifest_row()["health_check"]["expect_status"] == 200
