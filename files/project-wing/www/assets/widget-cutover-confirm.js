/* Wing — Coexistence cutover + cleanup UI.
 *
 * Cutover is destructive, so we require a typed confirmation ("CUTOVER") before
 * submitting. Also updates TTL countdowns every second.
 */
(function () {
	'use strict';

	const API = '/api/v1';
	const CONFIRM_PHRASE = 'CUTOVER';

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

	// ── Modal state ──
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

	function onEsc(e) { if (e.key === 'Escape') modal.close(); }

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

		updateTtls();
		setInterval(updateTtls, 1000);
	}

	if (document.readyState === 'loading') {
		document.addEventListener('DOMContentLoaded', init);
	} else {
		init();
	}
})();
