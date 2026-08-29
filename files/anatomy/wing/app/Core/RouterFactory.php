<?php

declare(strict_types=1);

namespace App\Core;

use Nette;
use Nette\Application\Routers\RouteList;

final class RouterFactory
{
	use Nette\StaticClass;

	public static function createRouter(): RouteList
	{
		$router = new RouteList;

		// API v1 routes (must be before dashboard catch-all)
		$api = $router->withModule('Api');
		$api->addRoute('api/v1/dashboard/summary', 'Dashboard:summary');
		$api->addRoute('api/v1/dashboard/timeline', 'Dashboard:timeline');
		$api->addRoute('api/v1/components[/<id>]', 'Components:default');
		$api->addRoute('api/v1/scan/state', 'Scan:state');
		$api->addRoute('api/v1/scan/cycles', 'Scan:cycles');
		$api->addRoute('api/v1/scan/cycle', 'Scan:cycle');
		$api->addRoute('api/v1/scan/component/<id>', 'Scan:component');
		$api->addRoute('api/v1/scan/config', 'Scan:config');
		$api->addRoute('api/v1/scan/rotation', 'Scan:rotation');
		$api->addRoute('api/v1/scan/probe/<name>/complete', 'Scan:probeComplete');
		$api->addRoute('api/v1/advisories[/<id>]', 'Advisories:default');
		$api->addRoute('api/v1/remediation/bulk-status', 'Remediation:bulkStatus');
		$api->addRoute('api/v1/remediation/next-id', 'Remediation:nextId');
		$api->addRoute('api/v1/remediation[/<id>]', 'Remediation:default');
		$api->addRoute('api/v1/pentest/patches[/<id>]', 'Pentest:patches');
		$api->addRoute('api/v1/pentest/findings/<id>', 'Pentest:findingUpdate');
		$api->addRoute('api/v1/pentest/targets/<id>/areas-tested', 'Pentest:areasTested');
		$api->addRoute('api/v1/pentest/targets/<id>/areas-planned', 'Pentest:areasPlanned');
		$api->addRoute('api/v1/pentest/targets/<id>/findings', 'Pentest:findings');
		$api->addRoute('api/v1/pentest/targets[/<id>]', 'Pentest:targets');

		// Hub API (public — service names/ports are non-sensitive, nginx still
		// gates the /hub browser page behind Authentik proxy auth)
		$api->addRoute('api/v1/hub/systems[/<id>]', 'Hub:systems');
		$api->addRoute('api/v1/hub/health', 'Hub:health');

		// State & Migration Framework API (agent 7)
		// Events: POST = ingestion (HMAC), GET = paginated query (bearer).
		$api->addRoute('api/v1/events', 'Events:default');
		// Notifications read (W5-A2, 2026-05-26): GET = list (bearer). Creation
		// stays on the Bone HMAC path; this is the read the scout agent needs
		// for its severity-spike signal (previously 404 → un-evaluable).
		$api->addRoute('api/v1/notifications', 'Notifications:default');
		// A13.2 (2026-05-07): Prometheus metrics surface scraped by Alloy.
		// Anonymous read; bound to 127.0.0.1:9000 only (Caddyfile).
		$api->addRoute('api/v1/metrics', 'Metrics:default');
		$api->addRoute('api/v1/state/services[/<id>]', 'State:services');
		$api->addRoute('api/v1/state/sync', 'State:sync');
		$api->addRoute('api/v1/state', 'State:default');
		// B3: the migration-author producer. /authored BEFORE the general
		// /<id> + [/<id>] forms (Nette first-match-wins) so 'authored' isn't
		// swallowed as a migration id.
		$api->addRoute('api/v1/migrations/authored', 'Migrations:authored');
		$api->addRoute('api/v1/migrations/<id>/preview', 'Migrations:preview');
		$api->addRoute('api/v1/migrations/<id>/apply', 'Migrations:apply');
		$api->addRoute('api/v1/migrations/<id>/rollback', 'Migrations:rollback');
		$api->addRoute('api/v1/migrations[/<id>]', 'Migrations:default');
		$api->addRoute('api/v1/upgrades/history', 'Upgrades:history');
		// W5-B2: planned-upgrade queue. /planned before /<service>; /queue
		// before the general /<service>/<recipe> (Nette is first-match).
		$api->addRoute('api/v1/upgrades/planned', 'Upgrades:planned');
		$api->addRoute('api/v1/upgrades/<service>/<recipe>/queue', 'Upgrades:queue');
		// B3: plan-choice branch (migration vs coexist). Before the general
		// /<service>/<recipe> form (first-match-wins).
		$api->addRoute('api/v1/upgrades/<service>/<recipe>/plan-choice', 'Upgrades:planChoice');
		$api->addRoute('api/v1/upgrades/<service>/<recipe>/plan', 'Upgrades:plan');
		$api->addRoute('api/v1/upgrades/<service>/<recipe>/apply-detached', 'Upgrades:applyDetached');
		$api->addRoute('api/v1/upgrades/<service>/<recipe>/apply', 'Upgrades:apply');
		$api->addRoute('api/v1/upgrades/<service>/<recipe>', 'Upgrades:recipe');
		$api->addRoute('api/v1/upgrades/<service>', 'Upgrades:service');
		$api->addRoute('api/v1/upgrades', 'Upgrades:default');
		// Patches — first-class sibling of upgrades (nested pentest/patches kept
		// for backward compat, see PentestPresenter::actionPatches).
		$api->addRoute('api/v1/patches/history', 'Patches:history');
		$api->addRoute('api/v1/patches/<id>/plan', 'Patches:plan');
		$api->addRoute('api/v1/patches/<id>/apply', 'Patches:apply');
		$api->addRoute('api/v1/patches/<id>/events', 'Patches:events');
		$api->addRoute('api/v1/patches[/<id>]', 'Patches:default');
		// W5-B5 planned-coexistence queue. /planned before /<service>; /queue
		// before /<service>/provision (Nette is first-match).
		$api->addRoute('api/v1/coexistence/planned', 'Coexistence:planned');
		$api->addRoute('api/v1/coexistence/<service>/queue', 'Coexistence:queue');
		$api->addRoute('api/v1/coexistence/<service>/provision', 'Coexistence:provision');
		$api->addRoute('api/v1/coexistence/<service>/cutover', 'Coexistence:cutover');
		// B3: toggle-as-primary / deactivate-secondary / cancel-queued. The
		// reversible lifecycle verbs (proxy promote/deactivate to Bone, cancel is
		// Wing-DB-only). Before /cleanup/<tag> + the /<service> catch-alls.
		$api->addRoute('api/v1/coexistence/<service>/promote', 'Coexistence:promote');
		$api->addRoute('api/v1/coexistence/<service>/deactivate', 'Coexistence:deactivate');
		// A4 (Q3): manual re-runnable "Copy data" into a secondary (tag in body,
		// uniform with promote/deactivate). Before /cleanup/<tag> + catch-alls.
		$api->addRoute('api/v1/coexistence/<service>/copy-data', 'Coexistence:copyData');
		$api->addRoute('api/v1/coexistence/<service>/cancel', 'Coexistence:cancel');
		$api->addRoute('api/v1/coexistence/<service>/cleanup/<tag>', 'Coexistence:cleanup');
		$api->addRoute('api/v1/coexistence', 'Coexistence:default');

		// Pulse — scheduled-job catalog + run history (Anatomy P0.2, 2026-05-04).
		// /pulse_jobs/due and /pulse_runs/<id>/finish must come before their
		// general [/<id>] siblings — Nette is first-match-wins.
		$api->addRoute('api/v1/pulse_jobs/due', 'Pulse:jobsDue');
		// §4b run-now (2026-08-06): the request is recorded here; the daemon
		// stays the only executor. Before the [/<id>] sibling, same reason.
		$api->addRoute('api/v1/pulse_jobs/<id>/run-now', 'Pulse:runNow');
		$api->addRoute('api/v1/pulse_jobs[/<id>]', 'Pulse:jobs');         // A7: POST = upsert (loader), GET = list/get
		$api->addRoute('api/v1/pulse_runs/<id>/finish', 'Pulse:runFinish');
		// Same first-match-wins reason: without this line "summary" would be
		// captured as an <id> and answer 404 for a run that does not exist.
		$api->addRoute('api/v1/pulse_runs/summary', 'Pulse:runSummary');
		$api->addRoute('api/v1/pulse_runs[/<id>]', 'Pulse:runs');

		// Cortex-lang executor — P1, read verbs, synchronous (2026-08-09).
		// No /status/<id>: a synchronous dispatch has no job to poll. That
		// route belongs to P3, when write verbs go async, and it goes ABOVE
		// these two when it lands (Nette is first-match-wins).
		$api->addRoute('api/v1/cortex/opcodes', 'CortexExecutor:opcodes');
		$api->addRoute('api/v1/cortex/execute', 'CortexExecutor:execute');

		// Agent inbox — the write half of the A9 spine (2026-08-08). An agent
		// asks, the run suspends, and the answer may arrive from any channel.
		// /answer and /cancel before the general [/<uuid>] sibling: same
		// first-match-wins reason as pulse_runs/summary above, and here the
		// cost of getting it wrong is an answer 404-ing instead of landing.
		$api->addRoute('api/v1/inbox/questions/<uuid>/answer', 'Inbox:answer');
		$api->addRoute('api/v1/inbox/questions/<uuid>/cancel', 'Inbox:cancel');
		$api->addRoute('api/v1/inbox/questions[/<uuid>]', 'Inbox:questions');

		// Gitleaks findings (Anatomy A7, 2026-05-06).
		// resolve must come before the general [/<id>] route.
		$api->addRoute('api/v1/gitleaks_findings/<id>/resolve', 'Gitleaks:resolve');
		$api->addRoute('api/v1/gitleaks_findings[/<id>]', 'Gitleaks:default');

		// GDPR Article 30 register (Track D, 2026-04-26).
		$api->addRoute('api/v1/gdpr/processing[/<id>]', 'Gdpr:processing');
		$api->addRoute('api/v1/gdpr/dsar[/<id>]', 'Gdpr:dsar');
		// Specific breach-report route BEFORE the generic breaches route
		// (Nette first-match-wins) so /breaches/<id>/report isn't swallowed.
		$api->addRoute('api/v1/gdpr/breaches/<id>/report', 'Gdpr:breachReport');
		$api->addRoute('api/v1/gdpr/breaches[/<id>]', 'Gdpr:breaches');
		// Audit hash-chain integrity (gov P1) — Api\AuditPresenter (distinct
		// from the browser Audit:default).
		$api->addRoute('api/v1/audit/verify', 'Audit:verify');
		$api->addRoute('api/v1/gdpr/export.csv', 'Gdpr:exportCsv');

		// Public homepage (no auth — nginx exempts exact /)
		$router->addRoute('', 'Homepage:default');

		// Dashboard routes (browser, behind Authentik proxy auth)
		// BATCH 5 — custom preloader splash. /hub/splash BEFORE the catch-all
		// 'hub' so the first-match-wins router hits the interstitial route. The
		// presenter bounces straight to Hub:default when the preloader flag is
		// off (dormant default) or `?skip_splash=1` is set.
		$router->addRoute('hub/splash', 'Hub:splash');
		$router->addRoute('hub', 'Hub:default');
		$router->addRoute('dashboard', 'Dashboard:default');
		$router->addRoute('pentest', 'Pentest:default');
		$router->addRoute('remediation', 'Remediation:default');
		$router->addRoute('help', 'Help:default');

		// State & Migration Framework browser routes (agent 7)
		// B4c: operator review verbs for the agent-authored proposals (the
		// /migrations "Proposed" column). mark-reviewed/mark-rejected flip
		// review_status in_review/rejected (NEVER merged — that's the forge's
		// GATE-2 write). Specific verb routes BEFORE migrations/<id> so the
		// first-match-wins router doesn't swallow 'mark-reviewed' as a detail id.
		$router->addRoute('migrations/<id>/mark-reviewed', 'Migrations:markReviewed');
		$router->addRoute('migrations/<id>/mark-rejected', 'Migrations:markRejected');
		$router->addRoute('migrations/<id>', 'Migrations:detail');
		$router->addRoute('migrations', 'Migrations:default');
		$router->addRoute('upgrades/<service>/<recipe>/queue', 'Upgrades:queueUpgrade');
		// B4b: plan-choice modal commit target (migration in-place vs coexist).
		// Browser CSRF form POSTs here; before /<service> + /<service>/<recipe>
		// forms so 'plan-choice' isn't swallowed (Nette first-match-wins).
		$router->addRoute('upgrades/<service>/<recipe>/plan-choice', 'Upgrades:planChoice');
		// A3.2 (Q5/2026-06-16): Tier-1 "Promote to migration" button → fires the
		// native AgentKit migration-author (OperatorTrigger spawn). POST-only,
		// CSRF-gated; before the /<service> catch-all (first-match-wins). The
		// session is observed via the existing /api/v1/agent-sessions/<uuid> poll
		// — no new API route. Spawns the migration YAML + version bump write; the
		// review MR (GATE 2) is the wall, nothing goes live.
		$router->addRoute('upgrades/<service>/<recipe>/promote-to-migration', 'Upgrades:promoteToMigration');
		// F3 (2026-06-18): Tier-1 "Unqueue" control on a planned upgrade — resets
		// the queued row (planned → cancelled) so the operator can re-run the
		// plan-choice flow to TEST it, via the machinery (not a hand DB poke).
		// POST-only, CSRF-gated; before the /<service> catch-all (first-match-wins).
		$router->addRoute('upgrades/<service>/cancel-planned', 'Upgrades:cancelPlanned');
		$router->addRoute('upgrades/<service>', 'Upgrades:service');
		$router->addRoute('upgrades', 'Upgrades:default');
		$router->addRoute('timeline', 'Timeline:default');
		// Pulse job health (browser). The API half above has existed since
		// 2026-05-04 and recorded every run; nothing rendered them, so a job
		// failing on every fire since 2026-07-14 was invisible.
		$router->addRoute('pulse', 'Pulse:default');
		// B4c: reversible coexistence toggle verbs (browser, operator path). The
		// authoritative toggle-as-primary / deactivate-secondary / cancel-queued
		// controls. Specific routes BEFORE the bare 'coexistence' catch-all so the
		// first-match-wins router hits the verb form first.
		$router->addRoute('coexistence/<service>/toggle-primary', 'Coexistence:togglePrimary');
		$router->addRoute('coexistence/<service>/deactivate-secondary', 'Coexistence:deactivateSecondary');
		// A4 (Q3): manual re-runnable "Copy data" into a secondary track. Before
		// the bare 'coexistence' catch-all (first-match-wins).
		$router->addRoute('coexistence/<service>/copy-data', 'Coexistence:copyData');
		$router->addRoute('coexistence/<service>/cancel', 'Coexistence:cancel');
		$router->addRoute('coexistence', 'Coexistence:default');

		// GDPR browser route (Track D, 2026-04-26)
		$router->addRoute('gdpr', 'Gdpr:default');

		// Conductor inbox (Anatomy A8.c, 2026-05-07)
		//
		// THE TWO VERB ROUTES BELOW WERE MISSING UNTIL 2026-08-08, and the
		// consequence was silent: Nette renders an unroutable {plink} as `#`,
		// so `/inbox`'s "Mark read" button carried `action="#"` — verified on
		// the live page — and posted to the current URL, which is a GET render.
		// Nothing was ever marked read. No error, no log, a button that looks
		// like a button.
		//
		// Found while adding `Inbox:answer`, which would have inherited exactly
		// the same fate: an Approve button that posts nowhere is worse than no
		// button, because the operator believes they decided. Same
		// specific-before-catch-all ordering as everywhere else in this file.
		$router->addRoute('inbox/mark-read/<uuid>', 'Inbox:markRead');
		$router->addRoute('inbox/answer/<uuid>', 'Inbox:answer');
		$router->addRoute('inbox', 'Inbox:default');
		// A11 RETIRED (2026-08-08): an approval is a kind='approval' question
		// — resolution in agent_questions (resolve-once conditional UPDATE),
		// lineage keeps the agent_approval_* event types, buttons on /inbox.
		// The bare URL survives as a permanent redirect so bookmarks and
		// muscle memory learn the successor; the approve/reject verb routes
		// died with ApprovalsPresenter (whose decision path could lose a
		// decision two silent ways: empty-secret early return + discarded
		// curl result). Pinned by test_approval_queue_event_backed.py.
		$router->addRoute('approvals', 'Inbox:approvals');

		// /questions (2026-08-28) — READ-ONLY ledger of the same rows: who
		// answered, via which channel, and how many expired unanswered. No
		// verb routes, by design: /inbox is the only place a question is
		// answered, and a second decision path is a second thing to audit.
		$router->addRoute('questions', 'Questions:default');

		// Q6 (2026-08-28): every agent's harness, read-only — you cannot
		// consent to what you cannot see. No verb routes: an editor that
		// WRITES the harness is the `harness` proposal kind wearing a browser.
		$router->addRoute('loop-editor', 'LoopEditor:default');

		// A10.c / X.1.c (2026-05-08): actor-attributed event browser.
		// Phase 5 ceremony pass criterion uses this view to verify the
		// conductor self-test produced rows with actor_id=conductor.
		$router->addRoute('audit', 'Audit:default');

		// GDPR breach register (gov P1) — Tier-1 read-only deadline view.
		// Specific /<id> detail BEFORE the list (first-match-wins).
		$router->addRoute('breaches/<id>', 'Breaches:detail');
		$router->addRoute('breaches', 'Breaches:default');

		// A12 (2026-05-07): Tier-1 platform control panel (big-red-button
		// emergency halt of all Pulse cron firing). Specific routes BEFORE
		// the catch-all 'admin' so the matcher hits the verb form first.
		$router->addRoute('admin/halt', 'Admin:halt');
		$router->addRoute('admin/resume', 'Admin:resume');
		$router->addRoute('admin', 'Admin:default');

		// AgentKit — AIT runtime (Anatomy A14, 2026-05-07).
		// Browser views: /agents (catalog), /agents/<name> (detail),
		// /agents/<name>/sessions/<uuid> (deep-dive). API surface:
		// /api/v1/agents/* + /api/v1/agent-sessions/<uuid>.
		// Specific routes BEFORE the catch-all <name> form so the matcher
		// hits the verb form first (Nette is first-match-wins).
		$router->addRoute('agents/<name>/sessions/<id>', 'Agents:session');
		$router->addRoute('agents/<name>/start', 'Agents:start');
		// W6.3 kill verb BEFORE the catch-all <name> (first-match-wins);
		// uuid travels as a query param: POST /agents/kill?uuid=…
		$router->addRoute('agents/kill', 'Agents:kill');
		$router->addRoute('agents/<name>', 'Agents:detail');
		$router->addRoute('agents', 'Agents:default');
		$api->addRoute('api/v1/agents[/<name>]', 'Agents:default');
		// /api/v1/agents/<name>/sessions accepts both GET (list) and POST
		// (operator-trigger spawn — A14 follow-up, 2026-05-07).
		$api->addRoute('api/v1/agents/<name>/sessions', 'Agents:sessions');
		$api->addRoute('api/v1/agent-sessions/<uuid>', 'AgentSessions:default');

		// A17 (2026-05-20): CI deploy trigger — HMAC-auth POST that
		// spawns `ansible-playbook --tags <allowlisted>` after a green
		// pipeline. Branch + tag allowlists enforced in the presenter.
		$api->addRoute('api/v1/deploy-trigger', 'DeployTrigger:default');

		// Users + Invitations console (Anatomy A15, 2026-05-17). Tier-1
		// only (UsersPresenter::startup gates the whole presenter). Mounts
		// the four browser views + the two POST mutators. Specific routes
		// (POST handlers + the parameterized 'created' view) BEFORE the
		// catch-all default so the first-match-wins router hits the verb
		// forms first.
		$router->addRoute('users/invite-create', 'Users:inviteCreate');
		$router->addRoute('users/invite', 'Users:invite');
		$router->addRoute('users/created', 'Users:created');
		$router->addRoute('users/invitations', 'Users:invitations');
		$router->addRoute('users/revoke', 'Users:revoke');
		$router->addRoute('users', 'Users:default');

		return $router;
	}
}
