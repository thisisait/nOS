/**
 * Wing Hub — silent SSO session pre-warmer (BATCH 5, custom preloader).
 *
 * sso-autologin-plan.md §"Custom preloader" → "Session warmer":
 *   on load redirect to /application/o/authorize/?client_id=wing&…&prompt=none
 *   (OIDC cookie dance); on 302 go to /hub or ?service=; on prompt=none
 *   FAILURE do NOT loop — fall back to the normal flow; 10s timeout → fallback
 *   + Retry; per-service ALLOWED_REDIRECT_HOSTS whitelist = only <svc>.<tld>
 *   + auth.<tld>.
 *
 * HONEST behaviour (plan §"Čestně k latenci"):
 *   - Repeat login (existing Authentik session): prompt=none returns fast →
 *     we bounce to the destination. The splash masks ~100-200ms.
 *   - First login (no session): prompt=none FAILS (login_required) → we do NOT
 *     retry/loop; we drop straight into the normal flow (the fallback URL,
 *     which carries ?skip_splash=1 so the splash never re-arms).
 *
 * Loop-safety: a single attempt per page navigation, guarded by a
 * sessionStorage one-shot flag AND a hidden-iframe probe (no top-level
 * navigation to the IdP for the silent attempt). The iframe either lands back
 * on our same-origin callback (success — readable) or stalls/errors
 * (failure → fallback). Either way we navigate exactly once.
 */
(function () {
	'use strict';

	var root = document.getElementById('hub-splash');
	if (!root) {
		return; // not on the splash page
	}

	var authentikDomain = (root.dataset.authentikDomain || '').trim();
	var tenantDomain = (root.dataset.tenantDomain || '').trim();
	var service = (root.dataset.service || '').trim();
	var timeoutMs = parseInt(root.dataset.timeoutMs, 10);
	if (!(timeoutMs > 0)) {
		timeoutMs = 10000; // plan pins a 10s preloader ceiling
	}
	var fallbackUrl = root.dataset.fallbackUrl || '/hub?skip_splash=1';

	// ── Per-service redirect-host whitelist ───────────────────────────────
	// ONLY <svc>.<tld> and auth.<tld> are permitted post-warm destinations.
	// Open-redirect defence: any ?service= host that isn't on the whitelist
	// is dropped and we fall back to the local /hub dashboard.
	var ALLOWED_REDIRECT_HOSTS = [];
	if (tenantDomain) {
		ALLOWED_REDIRECT_HOSTS.push('auth.' + tenantDomain);
		if (service) {
			// service may be a bare slug ("grafana") or a full host
			// ("grafana.dev.local"); normalise to <svc>.<tld>.
			var slug = service.split('.')[0];
			if (slug) {
				ALLOWED_REDIRECT_HOSTS.push(slug + '.' + tenantDomain);
			}
		}
	}

	function hostAllowed(host) {
		return ALLOWED_REDIRECT_HOSTS.indexOf(host) !== -1;
	}

	// The post-success destination. If a ?service= deep-link names a
	// whitelisted host, go there; otherwise the local dashboard.
	function destinationUrl() {
		if (service) {
			var slug = service.split('.')[0];
			var host = slug + '.' + tenantDomain;
			if (tenantDomain && hostAllowed(host)) {
				return 'https://' + host + '/';
			}
		}
		// Same-origin dashboard — strip the splash so we don't re-arm it.
		return '/hub';
	}

	var statusEl = document.getElementById('hub-splash-status');
	var fallbackEl = document.getElementById('hub-splash-fallback');
	var retryBtn = document.getElementById('hub-splash-retry');

	function showFallback(msg) {
		if (statusEl && msg) {
			statusEl.textContent = msg;
		}
		if (fallbackEl) {
			fallbackEl.hidden = false;
		}
	}

	// One-shot guard: never run the silent attempt more than once per
	// navigation. If we've already tried this page-load, go straight to the
	// normal flow — this is the hard NO-LOOP guarantee.
	var GUARD = 'hubSessionWarmAttempted';
	function alreadyAttempted() {
		try {
			return sessionStorage.getItem(GUARD) === '1';
		} catch (e) {
			return false; // private mode / blocked storage → treat as first try
		}
	}
	function markAttempted() {
		try {
			sessionStorage.setItem(GUARD, '1');
		} catch (e) { /* ignore */ }
	}
	function clearAttempt() {
		try {
			sessionStorage.removeItem(GUARD);
		} catch (e) { /* ignore */ }
	}

	function goToDestination() {
		clearAttempt();
		window.location.replace(destinationUrl());
	}

	// Fall back to the NORMAL flow without looping. The fallback URL carries
	// ?skip_splash=1 so the splash route bypasses straight to /hub and the
	// normal OIDC button / dashboard is reachable.
	function goToNormalFlow() {
		clearAttempt();
		window.location.replace(fallbackUrl);
	}

	function buildAuthorizeUrl() {
		// Silent OIDC authorize. prompt=none = "don't show UI; only succeed if a
		// session already exists". The redirect_uri is our SAME-ORIGIN splash
		// callback so the success landing is readable cross-frame.
		var redirectUri = window.location.origin + '/hub/splash?skip_splash=1';
		var params = [
			'client_id=wing',
			'response_type=code',
			'scope=' + encodeURIComponent('openid'),
			'prompt=none',
			'redirect_uri=' + encodeURIComponent(redirectUri)
		];
		return 'https://' + authentikDomain + '/application/o/authorize/?' + params.join('&');
	}

	function warm() {
		if (!authentikDomain) {
			// No IdP host configured → can't pre-warm; normal flow.
			goToNormalFlow();
			return;
		}
		if (alreadyAttempted()) {
			// Came back here after a prior attempt (e.g. the IdP bounced us to
			// the same-origin callback which still routes to the splash). Do
			// NOT re-fire prompt=none — that's the loop we must avoid.
			goToDestination();
			return;
		}
		markAttempted();

		var settled = false;
		function settle(fn) {
			if (settled) {
				return;
			}
			settled = true;
			fn();
		}

		// Hidden-iframe probe so the silent attempt never navigates the top
		// window. On a live session Authentik 302s the iframe to our
		// same-origin callback (load fires, same-origin → success). On
		// login_required it errors / stays on the IdP origin (cross-origin,
		// unreadable) and the timeout drives the fallback.
		var iframe = document.createElement('iframe');
		iframe.style.display = 'none';
		iframe.setAttribute('aria-hidden', 'true');

		var hardTimer = window.setTimeout(function () {
			settle(function () {
				try { iframe.parentNode && iframe.parentNode.removeChild(iframe); } catch (e) { /* ignore */ }
				// prompt=none did not resolve in time → first-login / no session.
				// Surface a Retry + skip fallback rather than looping.
				showFallback('Session not ready. Continue with the normal sign-in.');
			});
		}, timeoutMs);

		iframe.onload = function () {
			// The iframe loaded. If it landed back on OUR origin, the silent
			// auth succeeded (the callback is same-origin and readable). If it
			// is still on the IdP origin (cross-origin), reading .href throws →
			// treat as failure (login_required) and fall back — NO LOOP.
			var sameOrigin = false;
			try {
				var href = iframe.contentWindow.location.href;
				sameOrigin = href.indexOf(window.location.origin) === 0;
			} catch (e) {
				sameOrigin = false; // cross-origin → still on IdP → not signed in
			}
			settle(function () {
				window.clearTimeout(hardTimer);
				try { iframe.parentNode && iframe.parentNode.removeChild(iframe); } catch (e) { /* ignore */ }
				if (sameOrigin) {
					goToDestination();
				} else {
					// prompt=none FAILURE (login_required). Do NOT re-attempt.
					goToNormalFlow();
				}
			});
		};

		iframe.src = buildAuthorizeUrl();
		document.body.appendChild(iframe);
	}

	// Retry button: clear the one-shot guard and re-run the silent attempt
	// once. Still bounded by the same timeout + no-loop guard.
	if (retryBtn) {
		retryBtn.addEventListener('click', function () {
			if (fallbackEl) {
				fallbackEl.hidden = true;
			}
			if (statusEl) {
				statusEl.textContent = 'Warming session…';
			}
			clearAttempt();
			warm();
		});
	}

	warm();
})();
