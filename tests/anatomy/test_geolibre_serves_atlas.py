"""Anatomy gate — GeoLibre + the nos-atlas plugin is a real, off-by-default service.

2026-10-03: the operator opened atlas.<tenant> and got 404 — nothing served it;
nos-atlas only ran as `npm run dev` beside a throwaway container. This gate pins
the served shape:

  1. the role renders a compose fragment whose image is the digest pin;
  2. the plugin bundle mount is read-only and never under ~/projects (the dev
     checkout is copied into the data dir, not mounted);
  3. a manifest row routes atlas.<tenant> and a plugin gates it (forward_auth, tier 3);
  4. install_geolibre defaults to false and is wired from stack-up with both tags.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import jinja2
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
ROLE = REPO / "roles/pazny.geolibre"
PLUGIN = REPO / "files/anatomy/plugins/geolibre-base/plugin.yml"
DIGEST = "sha256:7c43f124f306d7c00c66660faf73eced043d6ddd749a06afb055ed223e79cebe"


def _defaults() -> dict:
    return yaml.safe_load((REPO / "default.config.yml").read_text())


def _fragment() -> dict:
    d = _defaults()
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    ctx = {
        "geolibre_image": d["geolibre_image"],
        "geolibre_version": d["geolibre_version"],
        "geolibre_port": d["geolibre_port"],
        "geolibre_data_dir": "/Users/op/nos/tenants/t/shared/geolibre/data",
        "nos_atlas_src_dir": "/Users/op/projects/nos-atlas",
        "stacks_shared_network": "shared_net",
        "geolibre_mem_limit": "512m",
        "geolibre_cpus": "0.5",
    }
    text = env.from_string((ROLE / "templates/compose.yml.j2").read_text()).render(**ctx)
    return yaml.safe_load(text)["services"]["geolibre"]


def test_fragment_runs_the_pinned_digest():
    svc = _fragment()
    assert svc["image"].startswith("ghcr.io/opengeos/geolibre"), svc["image"]
    assert svc["image"].endswith("@" + DIGEST), f"image is not digest-pinned: {svc['image']}"
    assert svc["environment"]["GEOLIBRE_SHARE_URL"] == "off", "projects must never leave the box"
    assert all(p.startswith("127.0.0.1:") for p in svc["ports"]), "bind loopback only"


def test_bundle_mount_is_read_only_and_not_the_dev_checkout():
    mounts = [v for v in _fragment()["volumes"] if "/plugins/nos-atlas" in v.split(":")[1]]
    assert mounts, "no nos-atlas drop-in mount"
    for m in mounts:
        host, _, mode = m.split(":")
        assert mode == "ro", f"plugin bundle must be mounted :ro — {m}"
        assert "/projects/" not in host, f"mounts the dev checkout — {m}"
    tasks = (ROLE / "tasks/main.yml").read_text()
    assert "nos_atlas_src_dir" in tasks and "ansible.builtin.copy" in tasks, (
        "the role must copy the bundle out of nos_atlas_src_dir")
    assert "failed_when: false" not in tasks


def test_off_by_default_and_wired_from_stack_up():
    d = _defaults()
    assert d["install_geolibre"] is False
    assert d["geolibre_domain"].startswith("atlas")
    stack_up = (REPO / "tasks/stacks/stack-up.yml").read_text()
    line = next(ln for ln in stack_up.splitlines() if "name: pazny.geolibre" in ln)
    assert "apply: { tags: ['geolibre'" in line and line.count("'geolibre'") >= 2, (
        f"include_role needs apply.tags AND tags: {line}")


def test_manifest_row_and_plugin_gate_it():
    rows = yaml.safe_load((REPO / "state/manifest.yml").read_text())["services"]
    row = next((r for r in rows if r["id"] == "geolibre"), None)
    assert row, "no state/manifest.yml row — Traefik never routes atlas.<tenant>"
    assert row["domain_var"] == "geolibre_domain" and row["port_var"] == "geolibre_port"
    assert row["install_flag"] == "install_geolibre"
    plugin = yaml.safe_load(PLUGIN.read_text())
    assert plugin["authentik"]["mode"] == "forward_auth"
    assert plugin["authentik"]["tier"] == 3
    assert plugin["ui-extension"]["hub_card"]["tier"] == 3


def test_the_image_service_worker_is_replaced_read_only():
    """2026-10-04: GeoLibre's PWA shell, cached by its service worker, loaded
    with an expired forward_auth sign-in; every request then hit the redirect."""
    mounts = _fragment()["volumes"]
    assert any(m.endswith(":/usr/share/nginx/html/sw.js:ro") for m in mounts), mounts


@pytest.mark.skipif(not shutil.which("node"), reason="runs the worker in node")
def test_the_replacement_worker_unregisters_and_clears_caches():
    harness = """
    const calls = []; const h = {};
    global.self = { addEventListener: (t, f) => (h[t] = f), skipWaiting: () => calls.push('skip'),
      registration: { unregister: async () => calls.push('unregister') },
      clients: { matchAll: async () => [{ url: 'https://atlas/x', navigate: (u) => calls.push('navigate ' + u) }] } };
    global.caches = { keys: async () => ['shell'], delete: async (n) => calls.push('delete ' + n) };
    require(process.argv[1]);
    let done; h.activate({ waitUntil: (p) => (done = p) });
    done.then(() => console.log(JSON.stringify(calls)));
    """
    out = subprocess.run(["node", "-e", harness, str(ROLE / "files/sw.js")],
                         capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == ["unregister", "delete shell", "navigate https://atlas/x"]
