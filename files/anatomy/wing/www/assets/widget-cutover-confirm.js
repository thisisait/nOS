/* Wing — Coexistence cutover + reversible primary/secondary toggle UI.
 *
 * Cutover + toggle-as-primary are destructive to live routing, so we require a
 * typed confirmation ("CUTOVER" / "PRIMARY") before submitting. Deactivate +
 * cancel are non-destructive (data kept / queued row only) → a window.confirm.
 *
 * A5 (§6.6) — asymmetric promote: the just-demoted prior primary (the known-good
 * rollback target) gets a ONE-CLICK window.confirm rollback button instead of the
 * typed-PRIMARY modal. Both hit the SAME toggle-primary endpoint via the shared
 * coex-toggle-form — the asymmetry is purely client-side confirm friction,
 * inverted to match risk (forward = less-proven new version = typed friction;
 * rollback = known-good = fast escape hatch).
 *
 * A4 (§5.2) — manual "Copy data": a one-click window.confirm button on each
 * secondary that carries a recorded source_migration_id. It runs the track's
 * migration data move into the SECONDARY's empty cluster (non-destructive → no
 * typed phrase) via the shared coex-copy-form → /coexistence/<svc>/copy-data.
 * Re-runnable: run it right before a promote for freshness.
 *
 * Two submit paths by design:
 *   - cutover / cleanup  → fetch() to the bearer-style /api/v1 surface (legacy).
 *   - toggle-primary / deactivate-secondary / copy-data / cancel-coexist (B4c +
 *     A4, operator path) → submit the real hidden CSRF <form> so the browser
 *     presenter handles the mutation and the server redirect+flash UX is
 *     preserved (no fetch).
 *
 * Also updates TTL countdowns every second.
 */
(function () {
	'use strict';

	const API = '/api/v1';
	const CONFIRM_PHRASE = 'CUTOVER';
	const TOGGLE_PHRASE = 'PRIMARY';

	// ── API helpers ──
	async function apiPost(path, body) {
		const res = await fetch(API + path, {
			method: 'POST',
			headers: { 'Accept': 'application/json', 'Content-Type': 'application/json' },
			body: body ? JSON.stringify(body) : '{}',
			credentials: 'same-origin'
		});
		if (!res.ok) throw new Error('HTTP ' + res.status);
		return res.json();
	}

	// ── Cutover modal state (legacy fetch path) ──
	const modal = {
		root: null, svcLabel: null, tagLabel: null, input: null, submit: null,
		service: null, tag: null, lastFocus: null,

		ensure() {
			this.root = document.getElementById('coex-cutover-modal');
			this.svcLabel = document.getElementById('coex-cutover-svc');
			this.tagLabel = document.getElementById('coex-cutover-tag');
			this.input = document.getElementById('coex-cutover-input');
			this.submit = document.getElementById('coex-cutover-submit');
			return !!this.root;
		},

		open(service, tag) {
			if (!this.ensure()) return;
			this.service = service;
			this.tag = tag;
			this.svcLabel.textContent = service;
			this.tagLabel.textContent = tag;
			this.input.value = '';
			this.input.setAttribute('aria-invalid', 'false');
			this.submit.disabled = true;
			this.lastFocus = document.activeElement;
			this.root.hidden = false;
			// Focus the input so the user can type immediately
			setTimeout(() => this.input.focus(), 0);
			document.addEventListener('keydown', onEsc);
		},

		close() {
			if (!this.root) return;
			this.root.hidden = true;
			this.service = null;
			this.tag = null;
			document.removeEventListener('keydown', onEsc);
			if (this.lastFocus && typeof this.lastFocus.focus === 'function') this.lastFocus.focus();
		}
	};

	function onEsc(e) { if (e.key === 'Escape') { modal.close(); toggleModal.close(); } }

	function onInput() {
		if (!modal.input) return;
		const ok = modal.input.value.trim() === CONFIRM_PHRASE;
		modal.input.setAttribute('aria-invalid', ok ? 'false' : (modal.input.value ? 'true' : 'false'));
		modal.submit.disabled = !ok;
	}

	async function onConfirm() {
		if (!modal.service || !modal.tag) return;
		modal.submit.disabled = true;
		modal.submit.textContent = 'Cutting over…';
		try {
			await apiPost(`/coexistence/${encodeURIComponent(modal.service)}/cutover`, { target_tag: modal.tag });
			window.location.reload();
		} catch (err) {
			alert('Cutover failed: ' + err.message);
			modal.submit.disabled = false;
			modal.submit.textContent = 'Confirm cutover';
		}
	}

	async function onCleanup(btn) {
		const service = btn.dataset.service;
		const tag = btn.dataset.tag;
		if (!window.confirm(`Clean up coexistence track "${tag}" for ${service}?\n\nThis removes the compose override, vhost, and data directory (with backup label).`)) return;
		btn.disabled = true;
		const orig = btn.textContent;
		btn.textContent = 'Working…';
		try {
			await apiPost(`/coexistence/${encodeURIComponent(service)}/cleanup/${encodeURIComponent(tag)}`);
			window.location.reload();
		} catch (err) {
			alert('Cleanup failed: ' + err.message);
			btn.disabled = false;
			btn.textContent = orig;
		}
	}

	// ── Toggle-as-primary modal state (B4c — submits a real CSRF form) ──
	const toggleModal = {
		root: null, svcLabel: null, tagLabel: null, input: null, submit: null,
		service: null, tag: null, lastFocus: null,

		ensure() {
			this.root = document.getElementById('coex-toggle-modal');
			this.svcLabel = document.getElementById('coex-toggle-svc');
			this.tagLabel = document.getElementById('coex-toggle-tag');
			this.input = document.getElementById('coex-toggle-input');
			this.submit = document.getElementById('coex-toggle-submit');
			return !!this.root;
		},

		open(service, tag) {
			if (!this.ensure()) return;
			this.service = service;
			this.tag = tag;
			this.svcLabel.textContent = service;
			this.tagLabel.textContent = tag;
			this.input.value = '';
			this.input.setAttribute('aria-invalid', 'false');
			this.submit.disabled = true;
			this.lastFocus = document.activeElement;
			this.root.hidden = false;
			setTimeout(() => this.input.focus(), 0);
			document.addEventListener('keydown', onEsc);
		},

		close() {
			if (!this.root) return;
			this.root.hidden = true;
			this.service = null;
			this.tag = null;
			document.removeEventListener('keydown', onEsc);
			if (this.lastFocus && typeof this.lastFocus.focus === 'function') this.lastFocus.focus();
		}
	};

	function onToggleInput() {
		if (!toggleModal.input) return;
		const ok = toggleModal.input.value.trim() === TOGGLE_PHRASE;
		toggleModal.input.setAttribute('aria-invalid', ok ? 'false' : (toggleModal.input.value ? 'true' : 'false'));
		toggleModal.submit.disabled = !ok;
	}

	// Submit the real hidden CSRF <form> → browser presenter handles the mutation
	// and redirects with a flash (no fetch — preserves the server redirect UX).
	function onToggleConfirm() {
		if (!toggleModal.service || !toggleModal.tag) return;
		const form = document.getElementById('coex-toggle-form');
		const tagInput = document.getElementById('coex-toggle-target-tag');
		if (!form || !tagInput) return;
		form.action = `/coexistence/${encodeURIComponent(toggleModal.service)}/toggle-primary`;
		tagInput.value = toggleModal.tag;
		toggleModal.submit.disabled = true;
		toggleModal.submit.textContent = 'Toggling…';
		form.submit();
	}

	// A5 (§6.6): one-click rollback to the just-demoted known-good prior primary.
	// Hits the SAME server endpoint as the typed-PRIMARY toggle (the shared
	// coex-toggle-form → /coexistence/<svc>/toggle-primary → promote_track); the
	// ONLY difference is a single window.confirm instead of the typed modal —
	// rollback returns to the lower-risk known-good version, so fast escape-hatch
	// friction (not typed friction) matches the risk. NOT the TOGGLE_PHRASE path.
	function onRollback(btn) {
		const service = btn.dataset.service;
		const tag = btn.dataset.tag;
		if (!window.confirm(`Roll back ${service} to track "${tag}"?\n\nThis re-promotes the just-demoted known-good primary. Live traffic routes to it on the next request (reversible).`)) return;
		const form = document.getElementById('coex-toggle-form');
		const tagInput = document.getElementById('coex-toggle-target-tag');
		if (!form || !tagInput) return;
		form.action = `/coexistence/${encodeURIComponent(service)}/toggle-primary`;
		tagInput.value = tag;
		btn.disabled = true;
		form.submit();
	}

	// A4 (§5.2): manual, re-runnable "Copy data" into a secondary track. Runs the
	// track's recorded migration data move (pg_dumpall → restore) into the
	// secondary's empty cluster, then stamps data_copied_at. Non-destructive
	// (writes only into the empty secondary) → a single window.confirm, no typed
	// phrase. Submits the shared coex-copy-form → /coexistence/<svc>/copy-data →
	// CoexistencePresenter::actionCopyData → Bone copy_data. Re-run before promote.
	function onCopyData(btn) {
		const service = btn.dataset.service;
		const tag = btn.dataset.tag;
		if (!window.confirm(`Copy data into ${service} track "${tag}"?\n\nThis runs the track's migration data move (pg_dumpall → restore) into the secondary's cluster. Re-runnable — run it right before Promote to capture the latest data. Nothing goes live (no pointer flip).`)) return;
		const form = document.getElementById('coex-copy-form');
		const tagInput = document.getElementById('coex-copy-tag');
		if (!form || !tagInput) return;
		form.action = `/coexistence/${encodeURIComponent(service)}/copy-data`;
		tagInput.value = tag;
		btn.disabled = true;
		form.submit();
	}

	function onDeactivate(btn) {
		const service = btn.dataset.service;
		const tag = btn.dataset.tag;
		if (!window.confirm(`Deactivate track "${tag}" for ${service}?\n\nThe container is stopped but its data + override are kept — re-promote it within the TTL to roll back. This refuses the active primary unless a failover target exists.`)) return;
		const form = document.getElementById('coex-deactivate-form');
		const tagInput = document.getElementById('coex-deactivate-tag');
		if (!form || !tagInput) return;
		form.action = `/coexistence/${encodeURIComponent(service)}/deactivate-secondary`;
		tagInput.value = tag;
		btn.disabled = true;
		form.submit();
	}

	function onCancelCoexist(btn) {
		const service = btn.dataset.service;
		const tag = btn.dataset.tag;
		if (!window.confirm(`Cancel the queued provision "${tag}" for ${service}?\n\nThe track was never provisioned — this only dequeues it (no container/data to remove).`)) return;
		const form = document.getElementById('coex-cancel-form');
		const tagInput = document.getElementById('coex-cancel-tag');
		if (!form || !tagInput) return;
		form.action = `/coexistence/${encodeURIComponent(service)}/cancel`;
		tagInput.value = tag;
		btn.disabled = true;
		form.submit();
	}

	// ── TTL countdown ──
	function formatDelta(ms) {
		if (ms <= 0) return 'expired';
		const s = Math.floor(ms / 1000);
		const d = Math.floor(s / 86400);
		const h = Math.floor((s % 86400) / 3600);
		const m = Math.floor((s % 3600) / 60);
		const sec = s % 60;
		if (d > 0) return `${d}d ${h}h`;
		if (h > 0) return `${h}h ${m}m`;
		if (m > 0) return `${m}m ${sec}s`;
		return `${sec}s`;
	}

	function updateTtls() {
		document.querySelectorAll('.coex-ttl[data-ttl-until]').forEach(node => {
			const until = Date.parse(node.dataset.ttlUntil);
			if (isNaN(until)) return;
			const delta = until - Date.now();
			const valueEl = node.querySelector('[data-role="ttl-value"]');
			if (valueEl) valueEl.textContent = formatDelta(delta);

			let urgency = 'normal';
			if (delta <= 0) urgency = 'expired';
			else if (delta <= 24 * 3600 * 1000) urgency = 'urgent';
			else if (delta <= 3 * 24 * 3600 * 1000) urgency = 'soon';
			node.setAttribute('data-urgency', urgency);
		});
	}

	// ── Delegation ──
	function init() {
		document.addEventListener('click', function (e) {
			const btn = e.target.closest('[data-action]');
			if (!btn) return;
			const action = btn.dataset.action;

			switch (action) {
				case 'cutover':
					e.preventDefault();
					modal.open(btn.dataset.service, btn.dataset.targetTag);
					break;
				case 'close-cutover':
					e.preventDefault();
					modal.close();
					break;
				case 'confirm-cutover':
					e.preventDefault();
					onConfirm();
					break;
				case 'cleanup-track':
					e.preventDefault();
					onCleanup(btn);
					break;
				// ── B4c reversible toggle verbs ──
				case 'toggle-primary':
					e.preventDefault();
					toggleModal.open(btn.dataset.service, btn.dataset.tag);
					break;
				// A5: one-click rollback (no typed phrase) → same toggle endpoint.
				case 'rollback-primary':
					e.preventDefault();
					onRollback(btn);
					break;
				case 'close-toggle':
					e.preventDefault();
					toggleModal.close();
					break;
				case 'confirm-toggle':
					e.preventDefault();
					onToggleConfirm();
					break;
				// A4: one-click copy-data (no typed phrase) → shared coex-copy-form.
				case 'copy-data':
					e.preventDefault();
					onCopyData(btn);
					break;
				case 'deactivate-secondary':
					e.preventDefault();
					onDeactivate(btn);
					break;
				case 'cancel-coexist':
					e.preventDefault();
					onCancelCoexist(btn);
					break;
			}
		});

		if (modal.ensure()) {
			modal.input.addEventListener('input', onInput);
			modal.root.addEventListener('click', function (e) {
				if (e.target === modal.root) modal.close();
			});
			// Enter key on valid input submits
			modal.input.addEventListener('keydown', function (e) {
				if (e.key === 'Enter' && !modal.submit.disabled) {
					e.preventDefault();
					onConfirm();
				}
			});
		}

		if (toggleModal.ensure()) {
			toggleModal.input.addEventListener('input', onToggleInput);
			toggleModal.root.addEventListener('click', function (e) {
				if (e.target === toggleModal.root) toggleModal.close();
			});
			toggleModal.input.addEventListener('keydown', function (e) {
				if (e.key === 'Enter' && !toggleModal.submit.disabled) {
					e.preventDefault();
					onToggleConfirm();
				}
			});
		}

		updateTtls();
		setInterval(updateTtls, 1000);
	}

	if (document.readyState === 'loading') {
		document.addEventListener('DOMContentLoaded', init);
	} else {
		init();
	}
})();
