"""One journey through Wing's pages: templates, links, Hub, dashboard, cortex handlers, /upgrades.

Merges eleven files (2026-11-08, roadmap gate-diet-role-journeys); every assert kept:
  test_wing_templates_resolve_case_sensitively, test_wing_latte_ratchet,
  test_every_button_posts_somewhere, test_wing_shows_drift_amber,
  test_dashboard_data_honesty, test_cortex_aggregate_and_show_run,
  test_cortex_meta_is_not_data, test_a_chain_is_one_action_not_many,
  test_hub_health_coverage, test_the_upgrade_matrix_compares_versions,
  test_os_update_surface.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
WING_ROOT = REPO / "files/anatomy/wing"
APP = WING_ROOT / "app"

needs_php = pytest.mark.skipif(shutil.which("php") is None, reason="php not installed on this runner")


# ── templates resolve case-sensitively ──────────────────────────────────────
# Nette looks in app/templates/; the dir is app/Templates/. On Linux every HTML
# page 404'd while the JSON API answered (spark1, 2026-10-19).

def test_the_directory_is_spelt_as_the_presenter_names_it():
    base = (APP / "Presenters" / "BasePresenter.php").read_text(encoding="utf-8")
    for fn in ("formatTemplateFiles", "formatLayoutTemplateFiles"):
        body = re.search(rf"function {fn}\(\): array\s*\{{(.*?)\n\t\}}", base, re.S)
        assert body, f"BasePresenter does not override {fn} — Nette would look in app/templates/"
        assert "'/Templates'" in body.group(1), f"{fn} must name app/Templates exactly"
    # The listing's spelling, not exists(): on a case-insensitive macOS volume `templates` always exists.
    names = {p.name for p in APP.iterdir()}
    assert "Templates" in names and "templates" not in names, sorted(names)
    assert (APP / "Templates" / "@layout.latte").is_file()


# ── the Latte surface may only shrink (ratchet) ─────────────────────────────
# Roadmap wing-organ-without-face: every human action moves to face; a new
# Latte page is a defect. Pinned BY NAME, one line each: adding one is red,
# deleting one without deleting its line here is red too.

TEMPLATES = {
    '@layout.latte',
    '@widgets/event-stream.latte',
    '@widgets/pending-migrations.latte',
    '@widgets/version-health.latte',
    'Admin/default.latte',
    'Agents/default.latte',
    'Agents/detail.latte',
    'Agents/session.latte',
    'Audit/default.latte',
    'Breaches/default.latte',
    'Breaches/detail.latte',
    'Coexistence/default.latte',
    'Dashboard/default.latte',
    'Gdpr/ClientRecords.latte',
    'Gdpr/default.latte',
    'Help/default.latte',
    'Homepage/default.latte',
    'Hub/default.latte',
    'Hub/splash.latte',
    'Inbox/default.latte',
    'LoopEditor/default.latte',
    'Migrations/default.latte',
    'Migrations/detail.latte',
    'Pentest/default.latte',
    'Pulse/default.latte',
    'Questions/default.latte',
    'Remediation/default.latte',
    'Timeline/default.latte',
    'Upgrades/@plan-choice-modal.latte',
    'Upgrades/default.latte',
    'Upgrades/service.latte',
    'Users/created.latte',
    'Users/default.latte',
    'Users/invitations.latte',
    'Users/invite.latte',
}

ROUTES = { # browser $router only; $api stays
    ' -> Homepage:default',
    'admin -> Admin:default',
    'admin/halt -> Admin:halt',
    'admin/resume -> Admin:resume',
    'agents -> Agents:default',
    'agents/<name> -> Agents:detail',
    'agents/<name>/sessions/<id> -> Agents:session',
    'agents/<name>/start -> Agents:start',
    'agents/kill -> Agents:kill',
    'approvals -> Inbox:approvals',
    'audit -> Audit:default',
    'breaches -> Breaches:default',
    'breaches/<id> -> Breaches:detail',
    'coexistence -> Coexistence:default',
    'coexistence/<service>/cancel -> Coexistence:cancel',
    'coexistence/<service>/copy-data -> Coexistence:copyData',
    'coexistence/<service>/deactivate-secondary -> Coexistence:deactivateSecondary',
    'coexistence/<service>/toggle-primary -> Coexistence:togglePrimary',
    'dashboard -> Dashboard:default',
    'gdpr -> Gdpr:default',
    'help -> Help:default',
    'hub -> Hub:default',
    'hub/splash -> Hub:splash',
    'inbox -> Inbox:default',
    'inbox/answer/<uuid> -> Inbox:answer',
    'inbox/mark-read/<uuid> -> Inbox:markRead',
    'loop-editor -> LoopEditor:default',
    'migrations -> Migrations:default',
    'migrations/<id> -> Migrations:detail',
    'migrations/<id>/mark-rejected -> Migrations:markRejected',
    'migrations/<id>/mark-reviewed -> Migrations:markReviewed',
    'pentest -> Pentest:default',
    'pulse -> Pulse:default',
    'questions -> Questions:default',
    'remediation -> Remediation:default',
    'timeline -> Timeline:default',
    'upgrades -> Upgrades:default',
    'upgrades/<service> -> Upgrades:service',
    'upgrades/<service>/<recipe>/plan-choice -> Upgrades:planChoice',
    'upgrades/<service>/<recipe>/promote-to-migration -> Upgrades:promoteToMigration',
    'upgrades/<service>/<recipe>/queue -> Upgrades:queueUpgrade',
    'upgrades/<service>/cancel-planned -> Upgrades:cancelPlanned',
    'users -> Users:default',
    'users/created -> Users:created',
    'users/invitations -> Users:invitations',
    'users/invite -> Users:invite',
    'users/invite-create -> Users:inviteCreate',
    'users/revoke -> Users:revoke',
}

RENDERS = {
    'Admin:renderDefault',
    'Agents:renderDefault',
    'Agents:renderDetail',
    'Agents:renderSession',
    'Audit:renderDefault',
    'Breaches:renderDefault',
    'Breaches:renderDetail',
    'Coexistence:renderDefault',
    'Dashboard:renderDefault',
    'Gdpr:renderClientRecords',
    'Gdpr:renderDefault',
    'Help:renderDefault',
    'Homepage:renderDefault',
    'Hub:renderDefault',
    'Hub:renderSplash',
    'Inbox:renderDefault',
    'LoopEditor:renderDefault',
    'Migrations:renderDefault',
    'Migrations:renderDetail',
    'Pentest:renderDefault',
    'Pulse:renderDefault',
    'Questions:renderDefault',
    'Remediation:renderDefault',
    'Timeline:renderDefault',
    'Upgrades:renderDefault',
    'Upgrades:renderService',
    'Users:renderCreated',
    'Users:renderDefault',
    'Users:renderInvitations',
    'Users:renderInvite',
}

ACTIONS = { # Inbox:actionApprovals is a redirect, not a verb
    'Admin:actionHalt',
    'Admin:actionResume',
    'Agents:actionKill',
    'Agents:actionStart',
    'Coexistence:actionCancel',
    'Coexistence:actionCopyData',
    'Coexistence:actionDeactivateSecondary',
    'Coexistence:actionTogglePrimary',
    'Inbox:actionAnswer',
    'Inbox:actionApprovals',
    'Inbox:actionMarkRead',
    'Migrations:actionMarkRejected',
    'Migrations:actionMarkReviewed',
    'Upgrades:actionCancelPlanned',
    'Upgrades:actionPlanChoice',
    'Upgrades:actionPromoteToMigration',
    'Upgrades:actionQueueUpgrade',
    'Users:actionInviteCreate',
    'Users:actionRevoke',
}

ASSETS = {
    'agent-session-poll.js',
    'coexistence.css',
    'dashboard.js',
    'hub-icons.css',
    'hub-icons.js',
    'hub-map.css',
    'hub-map.js',
    'hub-session-warmer.js',
    'hub.js',
    'inbox.js',
    'keyboard-nav.js',
    'lucide-slim.js',
    'lucide.min.js',
    'migrations.css',
    'migrations.js',
    'nav-overlay.js',
    'style.css',
    'timeline.css',
    'tokens.css',
    'upgrades-plan-choice.js',
    'upgrades.css',
    'users-invite-copy.js',
    'widget-cutover-confirm.js',
    'widget-timeline.js',
    'widget-version-health.js',
    'widgets.css',
}

PINNED = {"templates": TEMPLATES, "routes": ROUTES, "renders": RENDERS,
          "actions": ACTIONS, "assets": ASSETS}


def surface(wing: pathlib.Path) -> dict[str, set[str]]:
    app, www = wing / "app", wing / "www/assets"
    tpl, router = app / "Templates", app / "Core/RouterFactory.php"
    # either quote, any whitespace incl. newlines between the arguments
    routes = re.findall(r"""\$router->addRoute\(\s*(['"])(.*?)\1\s*,\s*(['"])(.*?)\3""",
                        router.read_text() if router.exists() else "", re.S)
    found = {"templates": {os.path.relpath(p, tpl).replace(os.sep, "/") for p in app.glob("**/*.latte")},
             "routes": {f"{m[1]} -> {m[3]}" for m in routes},
             "renders": set(), "actions": set(),
             "assets": {p.relative_to(www).as_posix() for p in www.glob("**/*") if p.is_file()}}
    pres = app / "Presenters"
    for p in pres.glob("**/*Presenter.php"):
        name = p.relative_to(pres).as_posix().removesuffix("Presenter.php")
        if name.startswith("Api/"):
            continue  # the $api module stays; only the browser surface is pinned
        for kind, rest in re.findall(r"function (render|action)(\w+)\s*\(", p.read_text()):
            found[kind + "s"].add(f"{name}:{kind}{rest}")
    return found


def drift(found: dict[str, set[str]]) -> list[str]:
    out = []
    for key, pinned in PINNED.items():
        out += [f"{key}: NEW {n} (a new Latte surface is a defect; build it in face)"
                for n in sorted(found[key] - pinned)]
        out += [f"{key}: GONE {n} (delete its line from {key.upper()} here)"
                for n in sorted(pinned - found[key])]
    return out


def test_wing_latte_surface_only_shrinks():
    assert drift(surface(WING_ROOT)) == []


def test_a_new_page_goes_red(tmp_path):
    (tmp_path / "app/Templates/Fixture").mkdir(parents=True)
    (tmp_path / "app/Templates/Fixture/default.latte").write_text("{block content}{/block}")
    assert "templates: NEW Fixture/default.latte (a new Latte surface is a defect; build it in face)" \
        in drift(surface(tmp_path))


def test_the_dead_static_dashboard_is_gone():
    # 928-line pre-Nette index.html: nothing served or linked it.
    assert not (WING_ROOT / "index.html").exists()


def test_the_scanner_has_no_side_doors(tmp_path):
    # Double quotes, a split call, a module subfolder, a template off Templates/.
    (tmp_path / "app/Core").mkdir(parents=True)
    (tmp_path / "app/Core/RouterFactory.php").write_text(
        '$router->addRoute("dq", "Dq:default");\n$router->addRoute(\n\t\'split\',\n\t\'Split:default\'\n);')
    (tmp_path / "app/Presenters/Mod").mkdir(parents=True)
    (tmp_path / "app/Presenters/Mod/SubPresenter.php").write_text("function renderDefault() {}")
    (tmp_path / "app/Presenters/Api").mkdir(parents=True)
    (tmp_path / "app/Presenters/Api/JsonPresenter.php").write_text("function actionDefault() {}")
    (tmp_path / "app/Other").mkdir(parents=True)
    (tmp_path / "app/Other/x.latte").write_text("")
    found = surface(tmp_path)
    assert {"dq -> Dq:default", "split -> Split:default"} <= found["routes"]
    assert "Mod/Sub:renderDefault" in found["renders"]
    assert not any(a.startswith("Api/") for a in found["actions"])  # $api stays out
    assert "../Other/x.latte" in found["templates"]


# ── every button posts somewhere ────────────────────────────────────────────
# Nette renders an unroutable {plink} as `#`: /inbox's Mark-read buttons posted
# to a GET render from May to 2026-08-08, nothing ever marked read, no error.
# Static: every {plink}/{link} target must be a RouterFactory route.

ROUTER = APP / "Core/RouterFactory.php"
TEMPLATE_DIR = APP / "Templates"

#: Targets Nette resolves without an explicit route entry.
BUILTIN = {"this", "Homepage:default", "Error:default"}


def routed_targets() -> set[str]:
    src = ROUTER.read_text(encoding="utf-8")
    # addRoute('mask', 'Presenter:action')
    return {m.group(1) for m in re.finditer(r"addRoute\(\s*'[^']*'\s*,\s*'([^']+)'", src)}


def linked_targets() -> dict[str, set[str]]:
    """target -> the templates that link it."""
    out: dict[str, set[str]] = {}
    for tpl in TEMPLATE_DIR.rglob("*.latte"):
        src = tpl.read_text(encoding="utf-8")
        for m in re.finditer(r"\{(?:plink|link)\s+([A-Za-z][A-Za-z0-9]*:[A-Za-z][A-Za-z0-9]*)", src):
            out.setdefault(m.group(1), set()).add(str(tpl.relative_to(WING_ROOT)))
    return out


def test_every_linked_action_has_a_route():
    routed = routed_targets()
    offenders = []
    for target, templates in sorted(linked_targets().items()):
        if target in BUILTIN or target in routed:
            continue
        offenders.append(f"{target}  ← {', '.join(sorted(templates))}")
    assert not offenders, (
        "template link(s) with no route in RouterFactory — Nette renders these "
        "as `action=\"#\"`, so the form posts to the current page and the "
        "action silently does not happen:\n  " + "\n  ".join(offenders)
        + "\n\nThis is how /inbox's Mark-read button did nothing from May to "
        "August 2026 without a single error."
    )


def test_the_router_declares_the_inbox_verbs():
    """Named explicitly: these two are the ones that were missing."""
    routed = routed_targets()
    for target in ("Inbox:markRead", "Inbox:answer"):
        assert target in routed, (
            f"{target} has no route. Its button will render action=\"#\" and "
            "post to a GET render."
        )


def test_state_changing_forms_are_post():
    """A GET link cannot be a decision — and requirePostMethod would reject it."""
    offenders = []
    for tpl in TEMPLATE_DIR.rglob("*.latte"):
        src = tpl.read_text(encoding="utf-8")
        for m in re.finditer(r"<a\b[^>]*\{plink\s+(\w+:(?:markRead|answer|approve|reject|cancel))", src):
            offenders.append(f"{tpl.relative_to(WING_ROOT)}: <a> to {m.group(1)}")
    assert not offenders, (
        "state-changing action(s) linked as an anchor rather than posted:\n  "
        + "\n  ".join(offenders)
    )


# ── Wing shows drift amber ──────────────────────────────────────────────────
# A declared findings code (tofu-drift rc=1) is drift: not red, not green.
# failingJobs() dropped those runs, so a drifting estate read as clean
# (operator 2026-10-04). The repository is EXECUTED against a sqlite stub.

DRIFT_STUB = r"""<?php
declare(strict_types=1);
namespace Nette\Database;
final class Explorer {
    public function __construct(private \PDO $pdo) {}
    public function query(string $sql): array {
        return array_map(fn($r) => (object) $r, $this->pdo->query($sql)->fetchAll(\PDO::FETCH_ASSOC));
    }
    public function table(string $t): object {
        $pdo = $this->pdo;
        return new class($pdo, $t) {
            public function __construct(private \PDO $pdo, private string $t) {}
            public function get(string $id): ?object {
                $s = $this->pdo->prepare("SELECT * FROM {$this->t} WHERE id = ?"); $s->execute([$id]);
                $r = $s->fetch(\PDO::FETCH_ASSOC); return $r ? (object) $r : null;
            }
        };
    }
}
namespace Probe;
require '%s';
$pdo = new \PDO('sqlite::memory:');
$pdo->exec("CREATE TABLE pulse_jobs (id TEXT PRIMARY KEY, findings_exit_codes TEXT, removed_at TEXT)");
$pdo->exec("CREATE TABLE pulse_runs (run_id TEXT, job_id TEXT, fired_at TEXT, exit_code INT)");
foreach ([['tofu:drift', '[1]'], ['loop:review', null], ['ok:job', '[1]']] as [$id, $codes]) {
    $pdo->prepare("INSERT INTO pulse_jobs (id, findings_exit_codes) VALUES (?, ?)")->execute([$id, $codes]);
}
foreach ([['1', 'tofu:drift', '2026-10-04T05:30:00Z', 1], ['2', 'loop:review', '2026-10-04T06:00:00Z', 2],
          ['3', 'ok:job', '2026-10-04T06:00:00Z', 0]] as $r) {
    $pdo->prepare("INSERT INTO pulse_runs VALUES (?, ?, ?, ?)")->execute($r);
}
$v = (new \App\Model\PulseRepository(new \Nette\Database\Explorer($pdo)))->latestVerdicts();
echo json_encode(array_map(fn($rows) => array_column($rows, 'job_id'), $v));
"""


@needs_php
def test_a_findings_code_is_drift_not_red_and_not_dropped(tmp_path):
    probe = tmp_path / "probe.php"
    probe.write_text(DRIFT_STUB % (APP / "Model/PulseRepository.php"), encoding="utf-8")
    r = subprocess.run(["php", "-d", "error_reporting=E_ALL", str(probe)],
                       capture_output=True, text=True, timeout=60, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout) == {"failing": ["loop:review"], "findings": ["tofu:drift"]}


def test_the_hub_renders_drift_in_amber():
    presenter = (APP / "Presenters/HubPresenter.php").read_text(encoding="utf-8")
    assert re.search(r"estateDrift\s*=\s*\$verdicts\['findings'\]", presenter), (
        "HubPresenter does not hand the findings bucket to the template")
    tpl = (APP / "Templates/Hub/default.latte").read_text(encoding="utf-8")
    tile = re.search(r'<div class="stat"[^\n]*\n\s*<div class="label">Estate drift</div>.*?(?=<div class="stat")', tpl, re.S)
    assert tile, "no Estate drift tile on /hub"
    assert "var(--orange)" in tile.group(0) and "var(--red)" not in tile.group(0) \
        and "var(--green)" not in tile.group(0), "drift must be amber: not red, not green"
    assert "$estateDrift" in tile.group(0)


# ── dashboard tells the truth about data freshness ──────────────────────────
# W6.2 (2026-06-10): the Scan-cycle KPI echoed "hourly" for on-demand scans,
# and every advisory card hardcoded recency-fresh (April glowed green in June).

DASH_PRESENTER = APP / "Presenters/DashboardPresenter.php"
DASH_TEMPLATE = APP / "Templates/Dashboard/default.latte"
SCAN_REPO = APP / "Model/ScanStateRepository.php"


def test_template_does_not_echo_config_schedule():
    src = DASH_TEMPLATE.read_text()
    assert "$state['config']['schedule']" not in src, (
        "the Scan-cycle KPI must not echo scan_config.schedule — that field "
        "says 'hourly' while scans are on-demand; show last-scan age instead"
    )
    assert "scanAgeDays" in src and "scanStale" in src


def test_stale_threshold_mirrors_drift_hook():
    src = DASH_PRESENTER.read_text()
    assert "> 14" in src, (
        "scanStale must use the same 14-day threshold as the CVE drift hook "
        "(hooks/playbook-end.d/20-cve-drift-check.sh) — one stale definition"
    )


def test_advisory_recency_is_computed_not_hardcoded():
    tpl = DASH_TEMPLATE.read_text()
    assert '<span class="recency recency-fresh"></span>' not in tpl, (
        "advisory recency dot is hardcoded fresh again"
    )
    assert "$adv['recency']" in tpl
    src = DASH_PRESENTER.read_text()
    # All four buckets reachable.
    for cls in ("recency-fresh", "recency-recent", "recency-stale", "recency-old"):
        assert cls in src, f"recencyClass lost the {cls} bucket"


def test_scan_state_exposes_latest_cycle_timestamp():
    src = SCAN_REPO.read_text()
    assert "latest_cycle_at" in src, (
        "getState must expose latest_cycle_at — the dashboard recency truth "
        "reads it"
    )


# ── cortex aggregate and show do real work ──────────────────────────────────
# Contract v3's read verbs: `aggregate` counts/sums/averages, `show` passes
# rows through with a render spec. Asked by running them, not by class presence.

ROWS = [{"track": "a", "h": 1}, {"track": "a", "h": "2"}, {"track": "b", "h": 5}, {"track": "b"}]


def run(handler: str, params: dict, rows: list | None, tmp_path: Path) -> dict:
    files = ["CortexStageResult", "ResolvedStage", "CortexContext",
             "Handler/CortexHandlerInterface", f"Handler/{handler}"]
    requires = "\n".join(f"require '{WING_ROOT}/app/Cortex/{f}.php';" for f in files)
    offered = "true" if rows is not None else "false"
    probe = tmp_path / "probe.php"
    probe.write_text(textwrap.dedent(f"""\
        <?php
        {requires}
        $h = new App\\Cortex\\Handler\\{handler}();
        $p = json_decode('{json.dumps(params)}', true);
        $in = json_decode('{json.dumps(rows or [])}', true);
        $r = $h->execute(new App\\Cortex\\ResolvedStage(0, $h->opcode(), false, [], $p),
            new App\\Cortex\\CortexContext('t', 'default', 'cx', null, $in, {offered}));
        echo json_encode($r->toArray());
    """), encoding="utf-8")
    out = subprocess.run(["php", "-d", "error_reporting=E_ALL", str(probe)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and not out.stderr, out.stderr or out.stdout
    return json.loads(out.stdout)


@needs_php
def test_aggregate_counts_sums_and_averages(tmp_path: Path) -> None:
    assert run("AggregateHandler", {"op": "count"}, ROWS, tmp_path)["rows"] == [{"count": 4}]
    grouped = run("AggregateHandler", {"op": "sum", "by": "track", "y": "h"}, ROWS, tmp_path)
    assert grouped["rows"] == [{"track": "a", "sum": 3}, {"track": "b", "sum": 5}]
    assert grouped["meta"] == {"skipped": 1}, "a row without a number must be counted as skipped"
    avg = run("AggregateHandler", {"op": "avg", "y": {"value": "h"}}, ROWS, tmp_path)
    assert avg["rows"] == [{"avg": 8 / 3}]


@needs_php
def test_aggregate_refuses_what_it_cannot_compute(tmp_path: Path) -> None:
    for params in ({"op": "median", "y": "h"}, {"op": "sum"}):
        assert run("AggregateHandler", params, ROWS, tmp_path)["code"] == "nothing_to_operate_by"
    assert run("AggregateHandler", {"op": "count"}, None, tmp_path)["code"] == "nothing_to_operate_by"


@needs_php
def test_show_passes_rows_through_with_a_render_spec(tmp_path: Path) -> None:
    got = run("ShowHandler", {"kind": "chart", "chart": "bar", "x": "track", "y": "h"}, ROWS, tmp_path)
    assert got["rows"] == ROWS
    assert got["meta"] == {"render": {"kind": "chart", "chart": "bar", "x": "track", "y": "h"}}
    assert run("ShowHandler", {"kind": "hologram"}, ROWS, tmp_path)["code"] == "nothing_to_operate_by"


# ── cortex meta is not data ─────────────────────────────────────────────────
# 2026-08-12, operator-verified: `map` appended a NOTE row that minted
# upstream_unreachable downstream; `filter where=tax` matched the handler-written
# `ns` mark. Meta rides CortexStageResult::$meta; marks are CortexRowProvenance::KEYS.

HANDLER = APP / "Cortex/Handler"

PRELUDE = [
    "app/Cortex/CortexStageResult.php",
    "app/Cortex/CortexContext.php",
    "app/Cortex/CortexRowProvenance.php",
    "app/Cortex/ResolvedStage.php",
    "app/Cortex/Handler/CortexHandlerInterface.php",
    "app/Cortex/Handler/FilterHandler.php",
]


def php(script: str, tmp_path: Path) -> subprocess.CompletedProcess:
    requires = "\n".join(f"require '{WING_ROOT}/{p}';" for p in PRELUDE)
    f = tmp_path / "probe.php"
    f.write_text(f"<?php\n{requires}\n{script}\n", encoding="utf-8")
    return subprocess.run(["php", "-d", "error_reporting=E_ALL", str(f)],
                          capture_output=True, text=True, timeout=60)


@needs_php
def test_meta_rides_the_result_not_the_rows(tmp_path: Path) -> None:
    out = php(textwrap.dedent("""\
        $r = App\\Cortex\\CortexStageResult::read(
            [['id' => 'x']], 3, ['truncated_input' => 7]);
        $a = $r->toArray();
        echo count($a['rows']) === 1
            && ($a['meta']['truncated_input'] ?? null) === 7 ? 'OK' : 'BAD';
        // Empty meta must not even appear — absent, not declared-empty.
        $b = App\\Cortex\\CortexStageResult::read([])->toArray();
        echo array_key_exists('meta', $b) ? '-LEAK' : '-CLEAN';
    """), tmp_path)
    assert out.stdout.strip() == "OK-CLEAN", (
        f"stdout: {out.stdout}\nstderr: {out.stderr}"
    )


@needs_php
def test_where_is_provenance_blind(tmp_path: Path) -> None:
    """Rows whose only 'tax' is the handler-written `ns` mark must NOT be kept
    by `where=tax`; a row whose DATA says tax must."""
    out = php(textwrap.dedent("""\
        $h = new App\\Cortex\\Handler\\FilterHandler();
        $stage = App\\Cortex\\ResolvedStage::fromAst([
            'index' => 1, 'opcode' => 'filter', 'mutating' => false,
            'operands' => [], 'params' => ['where' => 'tax'],
        ]);
        $ctx = new App\\Cortex\\CortexContext('t', 'default', 'cx-test', null, [
            ['id' => '01', 'name' => 'Taxonomy of forms', 'ns' => 'tax'],
            ['id' => '02', 'name' => 'Cosmology', 'ns' => 'tax'],
            ['id' => '03', 'name' => 'Cosmology', 'ns' => 'tax',
             'mappedFrom' => 'tax:01'],
        ], true);
        $r = $h->execute($stage, $ctx);
        // Only row 01 has 'tax' in its DATA (the name); 02/03 carry it solely
        // in provenance (ns, mappedFrom).
        echo count($r->rows) === 1 && $r->rows[0]['id'] === '01' ? 'OK' : 'KEPT-' . count($r->rows);
    """), tmp_path)
    assert out.stdout.strip() == "OK", (
        "`where` matched handler-written provenance (ns/mappedFrom) — the "
        "filter is matching the pipeline's own handwriting again.\n"
        f"stdout: {out.stdout}\nstderr: {out.stderr}"
    )


@needs_php
def test_every_handler_written_mark_is_declared() -> None:
    """A handler that writes a new row mark declares it in CortexRowProvenance::KEYS
    (the `$row + [...]` / `$child['k'] = ...` idioms only)."""
    prov = re.findall(
        r"'([A-Za-z]+)',",
        (APP / "Cortex/CortexRowProvenance.php").read_text(encoding="utf-8"),
    )
    assert "ns" in prov and "classifiedAs" in prov, "KEYS list moved — repoint"
    offenders = []
    for f in sorted(HANDLER.glob("*.php")):
        src = f.read_text(encoding="utf-8")
        # Rows a stage CONSTRUCTS whole (`$rows[] = [...]`) are data output, not
        # marks — reading those flagged resolve's own record fields once.
        attached: list[str] = []
        for m in re.finditer(r"\$row \+ \[(?s:(.*?))\]", src):
            attached += re.findall(r"'(\w+)' =>", m.group(1))
        attached += re.findall(r"\$child\['(\w+)'\] = ", src, re.M)
        for key in attached:
            if key not in prov:
                offenders.append(f"{f.name}: {key}")
    assert not offenders, (
        "handler writes row key(s) not declared in CortexRowProvenance::KEYS "
        "and not a copied entity fact — declare or justify:\n  "
        + "\n  ".join(sorted(set(offenders)))
    )


@needs_php
def test_no_handler_appends_a_note_row() -> None:
    """`'note' =>` inside a `$rows[] = [` block is the exact bytes both
    regressions shipped as."""
    offenders = []
    for f in sorted(HANDLER.glob("*.php")):
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(r"\$rows\[\]\s*=\s*\[(?s:(.*?))\];", src):
            if "'note'" in m.group(1):
                offenders.append(f.name)
    assert not offenders, (
        "a handler appends a commentary row into $rows — that flows downstream "
        "as INPUT and (proved live 2026-08-12) mints upstream_unreachable "
        f"against a healthy KEAP. Use CortexStageResult meta: {offenders}"
    )


@needs_php
def test_get_answers_an_outage_the_same_way_in_both_namespaces() -> None:
    src = (HANDLER / "GetHandler.php").read_text(encoding="utf-8")
    assert src.count("upstreamUnreachable") >= 2, (
        "GetHandler no longer answers a null node fetch with a typed absence in "
        "BOTH arms — the tax: fallback-row inconsistency is back (an unreachable "
        "KEAP flowing on as data that 'executed')."
    )


# ── a cortex chain is one action, not many ──────────────────────────────────
# 2026-08-30: the action id was minted inside the stage loop, so 404 stage events
# had 404 ids and a Grafana panel reported "the pipeline IR never ran" — measuring
# the bug. The id is minted once, before the loop. Retro-verified by moving it back.

EXEC = APP / "Presenters/Api/CortexExecutorPresenter.php"
CTX = APP / "Cortex/CortexContext.php"


def _execute_body() -> str:
    src = EXEC.read_text(encoding="utf-8")
    start = src.index("$brokenAt = null;")
    end = src.index("foreach ($stages as $raw)", start)
    return src[start:end], src[end:]


def test_the_action_id_is_minted_before_the_loop() -> None:
    before, after = _execute_body()
    assert "$actionId = 'cx-'" in before, (
        "the chain's action id is not minted before `foreach ($stages …)`. If it "
        "is minted inside, every stage gets its own key, and a SELECT on the "
        "lineage key returns one row however long the chain is — which is how "
        "a seven-stage pipeline came to be reported as never having run.")
    loop = after[:after.index("\n        }")] if "\n        }" in after else after
    assert "$actionId = 'cx-'" not in loop, (
        "the action id is minted inside the stage loop as well — one of the two "
        "wins at runtime and a reader cannot tell which")


def test_the_index_still_distinguishes_the_stages() -> None:
    """Sharing the id is only safe because `index` keeps the stages apart."""
    # The two STAGE audits only (a chain-level audit has no index); a substring
    # match anywhere stayed green when both lost it (`$brokenAt ??=` carries it).
    src = EXEC.read_text(encoding="utf-8")
    audits = [c for c in re.findall(r"\$this->audit\((.*?)\n\s*\]\);", src, re.S)
              if "cortex_stage_" in c]
    assert len(audits) == 2, (
        f"expected exactly the begin and finish stage audits, found {len(audits)}")
    for call in audits:
        assert "'index' => $stage->index" in call, (
            "a stage audit no longer carries `index`; with a shared action id "
            "that is the only thing saying which stage is which, and in what "
            "order:\n" + call[:200])


def test_the_contract_says_chain_not_stage() -> None:
    """Docblock and code have to move together."""
    doc = CTX.read_text(encoding="utf-8")
    assert "ONE PER CHAIN" in doc, (
        "CortexContext no longer states that the action id spans the chain — "
        "the sentence that was true of the intent and false of the code")
    assert "one per stage, minted before the" not in doc, (
        "the old per-stage promise is back in the docblock")


# ── Hub health coverage for URL-less backends ───────────────────────────────
# W6.4 (2026-06-10): 21/57 Hub systems sat "unchecked" forever (no public url,
# stack parents, DB-class). Pins health_url column, tcp:// probe, stack
# aggregation and the registry template's loopback health_urls.

SYSTEM_REPO = APP / "Model/SystemRepository.php"
INIT_DB = WING_ROOT / "bin/init-db.php"
REGISTRY_TPL = REPO / "templates/service-registry.json.j2"


def test_health_url_column_in_schema_and_alter_sweep():
    src = INIT_DB.read_text()
    assert "health_url      TEXT" in src, "fresh-create lost health_url"
    # Existing DBs must pick the column up via the idempotent sweep.
    sweep = src[src.index("addMissingColumns($db, 'systems'"):]
    assert "'health_url' => 'TEXT'" in sweep[:200]


def test_health_url_ingested_and_whitelisted():
    src = SYSTEM_REPO.read_text()
    assert "'health_url' => $svc['health_url'] ?? null" in src, (
        "ingestRegistry no longer maps health_url from the registry JSON"
    )
    wl = src[src.index("WRITABLE_FIELDS"):]
    wl = wl[:wl.index("];")]
    assert "'health_url'" in wl, (
        "upsert whitelist (SEC-7) dropped health_url — ingest would "
        "silently discard it"
    )


def test_probe_supports_tcp_scheme():
    src = SYSTEM_REPO.read_text()
    body = src[src.index("function probe("):]
    assert "str_starts_with($url, 'tcp://')" in body[:600]
    tcp = src[src.index("function probeTcp"):]
    assert "fsockopen" in tcp[:800]


def test_probe_all_prefers_health_url_and_aggregates_stacks():
    src = SYSTEM_REPO.read_text()
    body = src[src.index("function probeAll"):]
    assert "health_url" in body[:900], "probeAll no longer reads health_url"
    assert "aggregateStackHealth" in body[:1400], (
        "stack-parent aggregation dropped — 9 stack rows would return to "
        "eternal 'unchecked'"
    )
    agg = src[src.index("function aggregateStackHealth"):]
    # down if ANY checked child down; up if ALL checked children up.
    assert "$down > 0 ? 'down'" in agg


def test_registry_template_ships_backend_health_urls():
    src = REGISTRY_TPL.read_text()
    # Spot-pin the four classes: HTTP health endpoint, /metrics exporter,
    # tcp:// DB, and a plain HTTP UI.
    assert '"/-/healthy"' in src, "Prometheus health_url lost"
    assert '"http://127.0.0.1:9113/metrics"' in src, "exporter health_url lost"
    assert 'tcp://127.0.0.1:" ~ (mariadb_port' in src, "MariaDB tcp probe lost"
    assert 'uptime_kuma_port | default(3001))' in src
    # Count stays honest: at least 15 backends carry a probe target.
    assert src.count('"health_url"') >= 15, (
        f"only {src.count('\"health_url\"')} health_url entries left in the "
        "registry template (expected >= 15)"
    )


# ── the upgrade matrix compares versions ────────────────────────────────────
# Operator 2026-08-25: 22/29 catalog targets sat at or below running and read as
# the next step (`===` compare; GitLab offered 18.10.3 to 18.11.9 under a CVSS
# 9.4). Numeric compare, refuse non-versions, filter downgrades, say catalog-behind.

UPGRADE_REPOSITORY = APP / "Model/UpgradeRepository.php"

#: (installed, target, expected) — every one measured on this estate on
#: 2026-08-25 except the two synthetic refusals at the end.
#:   "ahead"   installed is past the target: NOT an upgrade
#:   "upgrade" target is genuinely above installed
#:   "equal"   the same version, differently spelled
#:   None      not a version on one side — the comparison must refuse
CASES = [
    ("16.15-alpine", "16", "ahead"),          # postgresql: read as upgradable for ever
    ("v0.162.19", "0.160.4", "ahead"),        # infisical: leading v + a real gap
    ("18.11.9-ce.0", "18.10.3-ce.0", "ahead"),   # gitlab: the downgrade it offered
    ("18.11.9-ce.0", "19.2.4-ce.0", "upgrade"),  # gitlab: the CVE floor it did not
    ("1.27.2", "1.27.0", "ahead"),            # gitea: REM-178's own shape
    ("12.4.4", "12.4.9", "upgrade"),          # grafana: REM-226, live today
    ("2.2.5", "2.2.5", "equal"),
    ("sha-b9a80dc", "sha-c1f2e3d", None),     # paperclip is pinned by build id
    ("latest", "1.2.3", None),
]


@pytest.mark.skipif(shutil.which("php") is None, reason="php absent — the comparison cannot run")
@pytest.mark.parametrize("installed,target,expected", CASES,
                         ids=[f"{a}_vs_{b}" for a, b, _ in CASES])
def test_versions_compare_the_way_the_estate_needs(installed, target, expected):
    script = (
        f'require "{UPGRADE_REPOSITORY}";'
        f'$r = App\\Model\\UpgradeRepository::compareVersions({installed!r}, {target!r});'
        'echo $r === null ? "null" : ($r > 0 ? "ahead" : ($r < 0 ? "upgrade" : "equal"));'
    ).replace("'", '"', 0)
    out = subprocess.run(["php", "-r", script], capture_output=True, text=True, timeout=60)
    got = out.stdout.strip()
    want = "null" if expected is None else expected
    assert got == want, (
        f"compareVersions({installed!r}, {target!r}) said {got!r}, expected {want!r}\n"
        f"{out.stderr[-300:]}")


def test_a_target_at_or_below_installed_is_not_an_upgrade():
    """`from_pattern` matching is not enough — it let GitLab offer 18.10.3 to 18.11.9."""
    src = UPGRADE_REPOSITORY.read_text(encoding="utf-8")
    body = src[src.index("public function matrix()"):]
    assert "array_filter($applicable" in body, (
        "the applicable set is no longer filtered against the installed "
        "version; a recipe whose from_pattern matches can target a downgrade")
    assert "compareVersions" in body, "the filter is not comparing versions"


def test_at_target_is_decided_numerically_not_by_string_equality():
    """Added after a mutation reverting `$atTarget` to `$inst === $stable` left
    every other assertion green."""
    src = UPGRADE_REPOSITORY.read_text(encoding="utf-8")
    body = src[src.index("$atTarget ="):]
    body = body[:body.index(";") + 1]
    assert "compareVersions" in body or "$cmpStable" in body, (
        "at-target is decided by string equality again. `16.15-alpine` never "
        f"equals `16`, so the row claims an upgrade for ever:\n  {body}")
    assert ">= 0" in body, (
        "at-target must be installed AT OR PAST the target, not merely equal — "
        "an estate ahead of its catalog is not mid-upgrade")


def test_the_row_distinguishes_up_to_date_from_catalog_behind():
    """'Nothing above you in the catalog' is about the RECIPES, not 'you are current'."""
    src = UPGRADE_REPOSITORY.read_text(encoding="utf-8")
    assert "'ahead_of_catalog'" in src, (
        "the matrix no longer reports when the catalog is behind the estate — "
        "the row then reads as up-to-date, which is a different claim")


def test_an_unreadable_comparison_never_hides_a_recipe():
    """`null` must not remove a recipe from the applicable set."""
    src = UPGRADE_REPOSITORY.read_text(encoding="utf-8")
    body = src[src.index("array_filter($applicable"):]
    body = body[:body.index("}));") + 4]
    assert "$cmp === null || $cmp > 0" in body, (
        "an uncomparable target is being filtered out; a refusal to compare "
        f"would then silently hide an available upgrade:\n{body}")


# ── /upgrades macOS-as-managed-upgrade surface ──────────────────────────────
# Increment 3c: osUpdateState() reads the ~/.nos continuation-plan + resume-result
# sidecars; the presenter exposes $osUpdate; the card renders nothing when absent.

UPGRADES_PRESENTER = APP / "Presenters" / "UpgradesPresenter.php"
UPGRADES_LATTE = APP / "Templates" / "Upgrades" / "default.latte"


def test_repository_reads_the_two_nos_sidecars():
    src = UPGRADE_REPOSITORY.read_text()
    assert "function osUpdateState(" in src
    assert "continuation-plan.json" in src and "os-resume-result.json" in src
    # defensive read: HOME, is_file, json_decode with JsonException, object guard
    assert "function readNosObject(" in src
    assert "getenv('HOME')" in src and "is_file(" in src
    assert "JSON_THROW_ON_ERROR" in src and "JsonException" in src


def test_presenter_exposes_os_update():
    src = UPGRADES_PRESENTER.read_text()
    assert "$this->template->osUpdate = $this->upgrades->osUpdateState()" in src


def test_latte_renders_armed_and_last_settle_gated():
    src = UPGRADES_LATTE.read_text()
    # the whole card is gated on $osUpdate (absent sidecar → nothing renders)
    assert "{if $osUpdate !== null}" in src
    assert "upg-os-card" in src
    assert "$osUpdate['armed']" in src and "$osUpdate['last_settle']" in src
    # the last-settle card shows the os_before -> os_after transition + clean/warn
    assert "os_before" in src and "os_after" in src
    assert "is-clean" in src and "is-warn" in src
