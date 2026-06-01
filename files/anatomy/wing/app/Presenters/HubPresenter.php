<?php

declare(strict_types=1);

namespace App\Presenters;

use App\Model\HubCardRepository;
use App\Model\SystemRepository;

/**
 * Hub — central dashboard showing all self-hosted systems.
 * Reads from SQLite `systems` table (populated by registry ingest +
 * manual/scan entries). Replaces the old "Components" tab — all data
 * is unified here. P1a overlays the plugin-harvested hub_card icon (+ tier)
 * so the per-plugin icons render and the viewer's tier is available for
 * RBAC-aware presentation.
 */
final class HubPresenter extends BasePresenter
{
	protected string $activeTab = 'hub';

	public function __construct(
		private SystemRepository $systems,
		private HubCardRepository $cards,
	) {
	}

	/**
	 * Backend services with no clickable browser UI; surface in /docker ps/
	 * Grafana Explore, not in /hub. (2026-05-29: caught by the URL audit gate
	 * as hard 404s on the public host — they have domain routes but no root.)
	 * TODO: promote to a `kind: backend` flag on the plugin manifest so the
	 * harvest can author this; today it's a small allow-list.
	 */
	private const BACKEND_ONLY_SLUGS = [
		'bluesky_pds', 'loki', 'tempo', 'prometheus', 'alloy', 'nginx',
		// QGIS Server serves WMS/WFS /ows endpoints — no browser root UI;
		// surfaced by the all-on URL audit gate 2026-05-29.
		'qgis_server',
	];

	public function renderDefault(): void
	{
		$stats = $this->systems->stats();
		$tree = $this->systems->tree();
		$byStack = $this->systems->byStack();

		// P1a — overlay the plugin hub_card icon (+ tier) onto each system by
		// normalised slug AND filter out non-clickable rows: TCP-only daemons
		// (postgresql/redis/mariadb/dnsmasq — no domain_url, only ip_url) and
		// backend services without a root UI. Render-time only; no DB write.
		$cardsBySlug = $this->cards->bySlug();
		$isClickable = static function (array $sys): bool {
			if (empty($sys['domain_url'])) {
				return false;   // TCP-only / no public host
			}
			if (in_array($sys['id'] ?? '', self::BACKEND_ONLY_SLUGS, true)) {
				return false;   // backend; surfaces via Grafana / clients
			}
			return true;
		};

		foreach ($byStack as $stack => $systems) {
			$kept = [];
			foreach ($systems as $sys) {
				if (!$isClickable($sys)) {
					continue;
				}
				$slug = strtolower(str_replace('_', '-', (string) ($sys['id'] ?? '')));
				if (isset($cardsBySlug[$slug])) {
					$sys['icon'] = $cardsBySlug[$slug]['icon'] ?? null;
					$sys['card_tier'] = $cardsBySlug[$slug]['tier'] ?? null;
				}
				$kept[] = $sys;
			}
			$byStack[$stack] = $kept;
		}
		// Drop now-empty stacks so the template doesn't show empty sections.
		$byStack = array_filter($byStack, static fn(array $s): bool => count($s) > 0);

		// Viewer's RBAC tier (1 = most privileged). Defaults to 1 (show all) when
		// no nos-group header is present, so /hub never blanks out for an
		// edge-token caller; the template can dim/badge by card_tier vs this.
		$this->template->viewerTier = $this->callerHasGroup('nos-providers') || $this->callerHasGroup('nos-admins') ? 1
			: ($this->callerHasGroup('nos-managers') ? 2
			: ($this->callerHasGroup('nos-users') ? 3
			: ($this->callerHasGroup('nos-guests') ? 4 : 1)));

		// Collect unique stacks and categories for filter buttons. Apply the
		// same clickable filter so the buttons' counts match the rendered grid
		// (no "infra (10)" when only 6 are shown).
		$stacks = [];
		$categories = [];
		foreach ($this->systems->list()['systems'] as $sys) {
			if ($sys['category'] === 'stack' || !$isClickable($sys)) {
				continue;
			}
			$s = $sys['stack'] ?? 'other';
			$stacks[$s] = ($stacks[$s] ?? 0) + 1;
			$c = $sys['category'] ?? 'other';
			$categories[$c] = ($categories[$c] ?? 0) + 1;
		}
		ksort($stacks);
		ksort($categories);

		$this->template->stats = $stats;
		$this->template->tree = $tree;
		$this->template->byStack = $byStack;
		$this->template->stacks = $stacks;
		$this->template->categories = $categories;
	}

	/**
	 * BATCH 5 — Custom preloader (sso-autologin-plan.md §"Custom preloader").
	 *
	 * Branded interstitial + silent session pre-warmer. On load,
	 * hub-session-warmer.js fires a `prompt=none` OIDC authorize against
	 * Authentik: if a session exists the 302 returns instantly (~100-200ms)
	 * and we bounce on to /hub (or ?service=); if NOT (first login) the
	 * prompt=none flow FAILS — the warmer must NOT loop, it falls back to the
	 * normal flow. A 10s timeout also drops to a Retry fallback.
	 *
	 * DORMANT by default: the whole mechanism is gated on
	 * `sso_enable_custom_preloader` (default false in default.config.yml,
	 * surfaced into the Wing runtime as the SSO_ENABLE_CUSTOM_PRELOADER env
	 * var). When the flag is off, the splash is bypassed entirely and the
	 * caller lands straight on the normal /hub dashboard — wiring the
	 * mechanism without turning it on.
	 *
	 * `?skip_splash=1` is an unconditional bypass (break-glass / direct link):
	 * it redirects to the dashboard regardless of the flag so a user can never
	 * be trapped on the splash. The same `?service=` passthrough is preserved
	 * so a deep-link target survives the bypass.
	 */
	public function renderSplash(): void
	{
		$req = $this->getHttpRequest();

		// Hard bypass — `?skip_splash=1` always lands on the dashboard, and the
		// preloader OFF (default) also bypasses so the splash stays dormant.
		$skip = (string) ($req->getQuery('skip_splash') ?? '') === '1';
		$enabled = getenv('SSO_ENABLE_CUSTOM_PRELOADER') === '1';
		if ($skip || !$enabled) {
			// Preserve a deep-link target across the bypass: ?service= names the
			// service the launcher tile pointed at. Forward it to /hub so the
			// dashboard (or a future per-service redirect) still has it.
			$service = (string) ($req->getQuery('service') ?? '');
			$this->redirect('Hub:default', $service !== '' ? ['service' => $service] : []);
			return;
		}

		// Build the OIDC `prompt=none` authorize target + the per-service
		// redirect-host whitelist the warmer JS enforces. The whitelist is
		// ONLY `<svc>.<tld>` + `auth.<tld>` — open-redirect defence
		// (sso-autologin-plan.md §"Open-redirect / CSRF").
		$authentikDomain = getenv('AUTHENTIK_DOMAIN') ?: 'auth.dev.local';
		$tld = getenv('TENANT_DOMAIN') ?: 'dev.local';
		$service = (string) ($req->getQuery('service') ?? '');

		$this->template->authentikDomain = $authentikDomain;
		$this->template->tenantDomain = $tld;
		// `service` is echoed into a data-attribute and consumed by the warmer
		// to compute its post-success destination; the JS re-validates it
		// against the host whitelist, never trusting it raw.
		$this->template->splashService = $service;
		// Surface the configured fallback timeout (ms) so the JS and the
		// presenter stay in lock-step. Defaults match default.config.yml
		// (sso_autologin_timeout_ms: 5000) but the plan's preloader spec pins a
		// 10s ceiling, so clamp to at least 10000 for the splash hard-timeout.
		$cfgTimeout = (int) (getenv('SSO_AUTOLOGIN_TIMEOUT_MS') ?: 5000);
		$this->template->splashTimeoutMs = max($cfgTimeout, 10000);
	}
}
