"""One list of services feeds Grafana, Wing /hub (and the face dock) and the landing page.

MEASURED 2026-10-19 (roadmap row one-service-directory): four surfaces listed
services from three roots — service-registry.json (manifest + install_* +
apps/*.yml), the plugin hub_card harvest (hub-cards.json, no apps), and a
hand-written list of ~30 `{% if install_x %}` cards in the Grafana dashboard.
Icons existed only on hub_card; the face dock's read of them was dead code
because Wing's API skipped the overlay and the backend filter.

The list is service-registry.json. "Public" = a row with a routed url that is
not `kind: backend`. For one config (profiles/all-on.yml plus every manifest
app) the playbook's own templates are RENDERED, Wing's own PHP is RUN, and each
surface must list exactly the ids it should: Grafana cards and Wing ?listed=1
(the dock's feed) = public; the landing page = public at RBAC tier 3-4; no
backend id on any of them; the registry carries each hub_card's icon.
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
HERE = Path(__file__).parent
sys.path[:0] = [str(REPO / "tools"), str(REPO / "files/anatomy"), str(HERE), str(REPO / "tests/apps")]
from module_utils import load_plugins as lp  # noqa: E402
from test_service_registry_is_the_installed_set import _flags  # noqa: E402

FILTERS = REPO / "filter_plugins/nos_installed.py"
WING = REPO / "files/anatomy/wing"
LANDING = REPO / "roles/pazny.landing"


def _apps() -> list[dict]:
    """apps_extra_services as pazny.apps_runner sets it: each app's registry_entry."""
    from test_render_module import _load_render_module  # noqa: PLC0415
    render = _load_render_module()
    out = []
    for p in sorted((REPO / "apps").glob("*.yml")):
        if not p.name.startswith("_"):
            out.append(render._registry_entry(p.stem, yaml.safe_load(p.read_text(encoding="utf-8")),
                                              f"{p.stem}.apps.dev.local"))
    return out


def _env() -> jinja2.Environment:
    import importlib.util  # noqa: PLC0415
    env = lp._jinja_env()
    spec = importlib.util.spec_from_file_location("nos_installed", FILTERS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    env.filters.update(mod.FilterModule().filters())
    env.filters.setdefault("regex_escape", re.escape)
    env.tests["search"] = lambda v, pat: re.search(pat, str(v)) is not None
    return env


def _ctx(env: jinja2.Environment) -> dict:
    flags = _flags("all-on.yml")
    ctx = dict(flags, apps_runner_enabled=True, apps_extra_services=_apps(), tenant_domain="dev.local",
               playbook_dir=str(REPO), ansible_facts={"hostname": "h", "env": {"HOME": "/h"}})

    def lookup(kind, name, default=None, **_):
        if kind == "file":
            return Path(name).read_text(encoding="utf-8")
        if kind == "template":
            return env.from_string(Path(name).read_text(encoding="utf-8")).render(ctx)
        return ctx.get(name, default)

    ctx["lookup"] = lookup
    return ctx


@pytest.fixture(scope="module")
def surfaces(tmp_path_factory) -> dict:
    env = _env()
    ctx = _ctx(env)
    reg = json.loads(ctx["lookup"]("template", str(REPO / "templates/service-registry.json.j2")))["services"]
    out = {"registry": reg}

    dash = json.loads(env.from_string(
        (REPO / "templates/grafana-service-registry-dashboard.json.j2").read_text(encoding="utf-8")).render(ctx))
    out["grafana"] = set(re.findall(r"data-id='([^']+)'", dash["panels"][0]["options"]["content"]))

    # pazny.landing: its own set_fact expression, every registry host routed.
    task = next(t for t in yaml.safe_load((LANDING / "tasks/main.yml").read_text())
                if "_landing_cards" in (t.get("ansible.builtin.set_fact") or {}))
    expr = task["ansible.builtin.set_fact"]["_landing_cards"].strip().removeprefix("{{").removesuffix("}}")
    lctx = dict(ctx, _landing_routed={"stdout_lines": sorted({s["domain"] for s in reg if s.get("domain")})})
    cards = env.compile_expression(expr)(**lctx)
    html = env.from_string((LANDING / "templates/index.html.j2").read_text(encoding="utf-8")).render(
        dict(lctx, _landing_cards=cards))
    out["landing"] = set(re.findall(r'data-id="([^"]+)"', html))
    out["landing_html"] = html

    # hub-cards.json + backend-slugs.json as wing-base renders them for this config.
    plugins = lp.discover(REPO / "files/anatomy/plugins")
    lp.run_aggregators(plugins, app_manifests=[], template_vars=ctx)
    wb = next(p for p in plugins if p.name == "wing-base")
    data = tmp_path_factory.mktemp("wing")
    for key in ("hub_cards", "backend_slugs"):
        spec = wb.manifest["provisioning"][key]
        body = env.from_string((wb.path / spec["template"]).read_text(encoding="utf-8")).render(
            dict(ctx, inputs=wb.inputs))
        (data / Path(spec["target"]).name).write_text(body, encoding="utf-8")
    out["hub_cards"] = json.loads((data / "hub-cards.json").read_text())["cards"]
    (data / "service-registry.json").write_text(json.dumps({"services": reg}), encoding="utf-8")
    out["wing_data"] = data
    return out


def _public(reg: list[dict]) -> set[str]:
    return {s["id"] for s in reg if s.get("url") and not s.get("backend")}


def _hidden(reg: list[dict]) -> set[str]:
    return {s["id"] for s in reg} - _public(reg)


def test_the_registry_carries_apps_and_hub_card_icons(surfaces) -> None:
    reg = {s["id"]: s for s in surfaces["registry"]}
    assert any(i.startswith("app_") for i in _public(surfaces["registry"])), "apps/*.yml never reached the list"
    wrong = sorted(c["slug"] for c in surfaces["hub_cards"]
                   if (r := reg.get(c["slug"].replace("-", "_"))) and r.get("icon") != c["icon"])
    assert not wrong, f"registry rows without their hub_card icon: {wrong}"
    backend = {s["id"] for s in surfaces["registry"] if s.get("backend")}
    assert {"prometheus", "loki", "qgis_server"} <= backend, "kind: backend never joined the registry"


def test_grafana_cards_are_the_public_list(surfaces) -> None:
    got, want = surfaces["grafana"], _public(surfaces["registry"])
    assert got == want, f"Grafana cards: missing {sorted(want - got)}, extra {sorted(got - want)}"


def test_landing_lists_public_tier_3_4_only(surfaces) -> None:
    reg = surfaces["registry"]
    want = {s["id"] for s in reg if s["id"] in _public(reg) and s.get("rbac_tier") in (3, 4)}
    got = surfaces["landing"]
    assert want, "no public tier 3-4 row in the list: the comparison below would be vacuous"
    assert got == want, f"landing: missing {sorted(want - got)}, extra {sorted(got - want)}"
    assert not got & _hidden(reg), f"landing shows backend / unrouted ids {sorted(got & _hidden(reg))}"
    assert not re.search(r":\d{2,5}[/\"']|127\.0\.0\.1", surfaces["landing_html"].split("<h2>Getting in")[0]), \
        "the directory cards carry a port or a loopback address"


PROBE = r"""
require __DIR__ . '/vendor/autoload.php';
use Nette\Database\{Connection, Explorer, Structure};
use Nette\Database\Conventions\DiscoveredConventions;
use Nette\Caching\Storages\MemoryStorage;

$dir = $argv[1];
putenv('WING_DATA_DIR=' . $dir);
exec(sprintf('php bin/init-db.php --data-dir=%s 2>&1', escapeshellarg($dir)), $o, $rc);
$conn = new Connection('sqlite:' . $dir . '/wing.db');
$storage = new MemoryStorage();
$structure = new Structure($conn, $storage);
$repo = new App\Model\SystemRepository(new Explorer($conn, $structure, new DiscoveredConventions($structure), $storage));
$repo->ingestRegistry($dir . '/service-registry.json');
$rows = App\Presenters\HubPresenter::listed($repo->list()['systems'], (new App\Model\HubCardRepository())->bySlug(),
    App\Presenters\HubPresenter::backendOnlySlugs());
echo json_encode(array_map(fn($s) => ['id' => $s['id'], 'icon' => $s['icon'] ?? null], $rows));
"""


def test_wing_listed_feed_is_the_public_list(surfaces) -> None:
    """Wing /hub and GET /api/v1/hub/systems?listed=1 (the face dock) share HubPresenter::listed."""
    if not (WING / "vendor/autoload.php").is_file() or not shutil.which("php"):
        pytest.skip("php or files/anatomy/wing/vendor missing — composer install there")
    api = (WING / "app/Presenters/Api/HubPresenter.php").read_text(encoding="utf-8")
    assert "HubPresenter::listed(" in api and "'listed'" in api, "the API does not serve the /hub list"
    probe = WING / "one-directory-probe.php"
    probe.write_text("<?php\n" + PROBE, encoding="utf-8")
    try:
        r = subprocess.run(["php", probe.name, str(surfaces["wing_data"])],
                           cwd=WING, capture_output=True, text=True, timeout=120)
    finally:
        probe.unlink(missing_ok=True)
    assert r.returncode == 0, r.stderr or r.stdout
    rows = json.loads(r.stdout.strip().splitlines()[-1])
    got, want = {x["id"] for x in rows}, _public(surfaces["registry"])
    assert got == want, f"Wing listed: missing {sorted(want - got)}, extra {sorted(got - want)}"
    assert all(x["icon"] for x in rows if x["id"] in {c["slug"].replace("-", "_") for c in surfaces["hub_cards"]}), \
        "Wing's listed rows lost the hub_card icon overlay"
