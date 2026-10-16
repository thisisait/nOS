"""Wing's browser (Latte) surface may only shrink.

WHY. Roadmap wing-organ-without-face: every human action moves to nOS face;
a new Latte page is a defect. Pinned BY NAME, one line each, so parallel
increment rows delete their own lines without conflicts. Adding one is red;
deleting one without deleting its line here is red too (the ratchet clicks).
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"

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
    tpl, www = wing / "app/Templates", wing / "www/assets"
    router = wing / "app/Core/RouterFactory.php"
    routes = re.findall(r"\$router->addRoute\('([^']*)',\s*'([^']*)'",
                        router.read_text() if router.exists() else "")
    found = {"templates": {p.relative_to(tpl).as_posix() for p in tpl.glob("**/*.latte")},
             "routes": {f"{m} -> {t}" for m, t in routes},
             "renders": set(), "actions": set(),
             "assets": {p.relative_to(www).as_posix() for p in www.glob("**/*") if p.is_file()}}
    for p in (wing / "app/Presenters").glob("*Presenter.php"):
        name = p.stem.removesuffix("Presenter")
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
    assert drift(surface(WING)) == []


def test_a_new_page_goes_red(tmp_path):
    (tmp_path / "app/Templates/Fixture").mkdir(parents=True)
    (tmp_path / "app/Templates/Fixture/default.latte").write_text("{block content}{/block}")
    assert "templates: NEW Fixture/default.latte (a new Latte surface is a defect; build it in face)" \
        in drift(surface(tmp_path))


def test_the_dead_static_dashboard_is_gone():
    # 928-line pre-Nette index.html: nothing served or linked it.
    assert not (WING / "index.html").exists()


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
