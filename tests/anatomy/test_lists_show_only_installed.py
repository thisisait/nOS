"""An app list shows what THIS host installed — nothing switched off, nothing never on.

MEASURED 2026-10-15 on a client host converged with profiles/core.yml: the
Authentik user library, Wing /hub and the face dock all listed applications
that host does not run. Three surfaces, two sources of truth to check against:

  * Authentik — 10-oidc-apps.yaml rendered from the loader's own harvest. Tier-2
    apps carried `enabled: true` whatever apps_runner_enabled said, and a service
    switched off simply dropped out of the blueprint, which never deletes.
  * Wing /hub and the face dock — both read Wing's `systems` table. Rows the
    one-shot security seed (bin/migrate.php, versions.json) inserted stayed
    enabled=1 beside the registry, so every scanned component was "an app".

"Installed" is the install_* flag resolved over the committed layers with the
profile on top (nos_identity.profile_layers) — what tools/services-status.py
reads. Each surface is RENDERED or RUN here, never grepped.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import jinja2
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "tools"), str(REPO / "files/anatomy")]
import nos_identity as ni  # noqa: E402
from module_utils import load_plugins as lp  # noqa: E402

WING = REPO / "files/anatomy/wing"
CORE = REPO / "profiles/core.yml"
BLUEPRINT = REPO / "files/anatomy/plugins/authentik-base/blueprints/10-oidc-apps.yaml.j2"


def _core() -> dict:
    """install_* plus the apps_runner switch, resolved for the core profile."""
    layers = ni.profile_layers(CORE)
    runner = ni.resolve_flag("apps_runner_enabled", layers)[-1][1].lower() == "true"
    return {**ni.install_flags(layers), "apps_runner_enabled": runner, "apps_skip": []}


class _Tags(yaml.SafeLoader):
    """authentik's !Find / !KeyOf are its loader's business, not this gate's."""


_Tags.add_multi_constructor("!", lambda loader, suffix, node: None)


class _Unset(jinja2.ChainableUndefined):
    def __str__(self) -> str:  # noqa: D105 — a token keeps the YAML well-formed
        return "unset"


def _apps() -> list[dict]:
    """apps/*.yml as nos_plugin_loader reads them (`_` and `.draft` skipped)."""
    return [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted((REPO / "apps").glob("*.yml"))
            if not p.name.startswith("_")]


def _authentik(tvars: dict) -> dict[str, list[str]]:
    """slug -> the `state`s 10-oidc-apps.yaml gives its application."""
    plugins = lp.discover(REPO / "files/anatomy/plugins")
    lp.run_aggregators(plugins, app_manifests=_apps(), template_vars=tvars)
    ab = next(p for p in plugins if p.name == "authentik-base")
    env = lp._jinja_env()
    env.undefined = _Unset
    ctx = dict(tvars, inputs=ab.inputs, authentik_engine="blueprint", authentik_oidc_apps=[])
    doc = yaml.load(env.from_string(BLUEPRINT.read_text(encoding="utf-8")).render(ctx), Loader=_Tags)
    out: dict[str, list[str]] = {}
    for e in doc["entries"]:
        if e.get("model") == "authentik_core.application":
            out.setdefault(e["identifiers"]["slug"], []).append(e.get("state"))
    return out


def _slug_flags() -> dict[str, str]:
    """slug -> the variable that installs it: the plugin block's own `enabled`
    expression, or apps_runner_enabled for a Tier-2 app."""
    out = {a["authentik"]["slug"]: "apps_runner_enabled" for a in _apps() if a.get("authentik")}
    for p in sorted((REPO / "files/anatomy/plugins").glob("*/plugin.yml")):
        block = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("authentik") or {}
        m = re.search(r"\{\{\s*(\w+)", str(block.get("enabled", "")))
        if m:
            out[block.get("slug") or p.parent.name.removesuffix("-base")] = m.group(1)
    return out


def test_authentik_presents_only_installed_applications() -> None:
    flags, owner = _core(), _slug_flags()
    leaked = sorted(s for s, st in _authentik(flags).items()
                    if "present" in st and flags.get(owner.get(s, "?")) is not True)
    assert not leaked, (
        f"core profile: Authentik would present applications for {leaked}, whose "
        "install flag is off — they land in every user's library")


def test_authentik_removes_a_service_switched_off() -> None:
    states = _authentik(_core())
    assert states.get("nextcloud") == ["absent"], (
        f"install_nextcloud is off in core, nextcloud renders {states.get('nextcloud')}: "
        "a blueprint never deletes what it stops listing, so a host that ran "
        "nextcloud keeps its application forever")
    assert states.get("keap") == ["present"], "keap is installed in core and must stay"


def test_authentik_presents_a_service_switched_on() -> None:
    assert _authentik(dict(_core(), install_nextcloud=True)).get("nextcloud") == ["present"]


# ── Wing /hub + face dock: both read Wing's systems table ────────────────────

PROBE = r"""
require __DIR__ . '/vendor/autoload.php';
use Nette\Database\{Connection, Explorer, Structure};
use Nette\Database\Conventions\DiscoveredConventions;
use Nette\Caching\Storages\MemoryStorage;

[$dir, $registry, $seed] = array_slice($argv, 1);
exec(sprintf('php bin/init-db.php --data-dir=%s 2>&1', escapeshellarg($dir)), $o, $rc);
exec(sprintf('php bin/migrate.php --json-dir=%s --data-dir=%s 2>&1', escapeshellarg($seed), escapeshellarg($dir)), $o, $rc);
$conn = new Connection('sqlite:' . $dir . '/wing.db');
$storage = new MemoryStorage();
$structure = new Structure($conn, $storage);
$repo = new App\Model\SystemRepository(new Explorer($conn, $structure, new DiscoveredConventions($structure), $storage));
$repo->ingestRegistry($registry);
$out = [];
foreach ($repo->list()['systems'] as $s) {
    $out[] = ['id' => $s['id'], 'enabled' => (int) $s['enabled'], 'category' => $s['category'],
              'hub' => method_exists(App\Presenters\HubPresenter::class, 'isListed')
                  ? App\Presenters\HubPresenter::isListed($s, []) : null];
}
echo json_encode($out);
"""


def _registry(flags: dict, dest: Path) -> set[str]:
    """Render templates/service-registry.json.j2 for `flags`; return its ids."""
    env = lp._jinja_env()
    env.undefined = jinja2.ChainableUndefined
    ctx = dict(flags, tenant_domain="dev.local", ansible_facts={"hostname": "h", "env": {"HOME": "/h"}})
    text = env.from_string((REPO / "templates/service-registry.json.j2").read_text(encoding="utf-8")).render(ctx)
    dest.write_text(text, encoding="utf-8")
    return {s["id"] for s in json.loads(text)["services"]}


def _wing(flags: dict, tmp: Path) -> tuple[set[str], list[dict]]:
    if not (WING / "vendor/autoload.php").is_file() or not shutil.which("php"):
        pytest.skip("php or files/anatomy/wing/vendor missing — composer install there")
    ids = _registry(flags, tmp / "service-registry.json")
    probe = WING / "lists-installed-probe.php"
    probe.write_text("<?php\n" + PROBE, encoding="utf-8")
    try:
        r = subprocess.run(["php", probe.name, str(tmp), str(tmp / "service-registry.json"),
                            str(REPO / "docs/llm/security")],
                           cwd=WING, capture_output=True, text=True, timeout=120)
    finally:
        probe.unlink(missing_ok=True)
    assert r.returncode == 0, r.stderr or r.stdout
    return ids, json.loads(r.stdout.strip().splitlines()[-1])


def test_face_reads_enabled_only_for_registry_rows(tmp_path: Path) -> None:
    """face's BFF keeps `enabled` rows (routes/bff/hub/+server.ts): that column
    must mean "in this host's registry", not "someone once inserted it"."""
    ids, rows = _wing(_core(), tmp_path)
    stray = sorted(r["id"] for r in rows
                   if r["enabled"] and r["category"] != "stack" and r["id"] not in ids)
    assert not stray, f"core host: enabled rows outside the registry reach the face dock: {stray}"


def test_wing_hub_lists_only_installed(tmp_path: Path) -> None:
    ids, rows = _wing(_core(), tmp_path)
    assert all(r["hub"] is not None for r in rows), "HubPresenter::isListed is the /hub filter; it is missing"
    listed = sorted(r["id"] for r in rows if r["hub"])
    assert set(listed) <= ids, f"core host: /hub lists {sorted(set(listed) - ids)}, not installed"


def test_wing_hub_lists_a_service_switched_on(tmp_path: Path) -> None:
    _, rows = _wing(dict(_core(), install_nextcloud=True), tmp_path)
    assert any(r["id"] == "nextcloud" and r["hub"] and r["enabled"] for r in rows)
