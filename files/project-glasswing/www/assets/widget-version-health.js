/* Glasswing — version-health dashboard widget.
 * Polls /api/v1/state every 30s and re-renders the top-5 services needing attention.
 * Safe DOM construction (no innerHTML).
 */
(function () {
	'use strict';

	const API = '/api/v1';
	const POLL_MS = 30000;
	const MAX_ROWS = 5;

	function el(tag, attrs, ...children) {
		const node = document.createElement(tag);
		if (attrs) Object.entries(attrs).forEach(([k, v]) => {
			if (k === 'className') node.className = v;
			else node.setAttribute(k, v);
		});
		children.forEach(c => {
			if (c == null) return;
			if (typeof c === 'string') node.appendChild(document.createTextNode(c));
			else node.appendChild(c);
		});
		return node;
	}

	function severityRank(sev) {
		return { critical: 4, breaking: 3, minor: 2, patch: 1 }[sev] || 0;
	}

	function selectTop(services) {
		const arr = Object.entries(services || {})
			.map(([id, svc]) => ({ id, ...svc }))
			.filter(s => s.upgrade_available && s.upgrade_available.version);
		arr.sort((a, b) => severityRank(b.upgrade_available.severity) - severityRank(a.upgrade_available.severity));
		return arr.slice(0, MAX_ROWS);
	}

	function renderRow(svc) {
		const row = el('div', { className: 'wvh-row', 'data-service': svc.id, 'data-severity': svc.upgrade_available.severity });
		const left = el('div', null,
			el('span', { className: 'wvh-svc' }, svc.id),
			svc.category ? el('span', { className: 'wvh-cat' }, svc.category) : null
		);
		const ver = el('div', { className: 'wvh-ver' },
			el('span', null, svc.installed || '?'),
			el('span', { className: 'arrow' }, ' → '),
			el('span', { className: 'to' }, svc.upgrade_available.version)
		);
		const badge = el('span', { className: 'sev-badge sev-' + svc.upgrade_available.severity },
			svc.upgrade_available.severity);
		row.appendChild(left);
		row.appendChild(ver);
		row.appendChild(badge);
		return row;
	}

	async function pollOnce() {
		const body = document.getElementById('wvh-body');
		const count = document.getElementById('wvh-count');
		const ind = document.getElementById('wvh-refresh');
		if (!body) return;

		try {
			const res = await fetch(API + '/state', { headers: { 'Accept': 'application/json' } });
			if (!res.ok) return;
			const state = await res.json();
			const top = selectTop(state.services || {});

			body.textContent = '';
			if (top.length === 0) {
				body.appendChild(el('div', { className: 'widget-empty' }, 'All services at target version.'));
			} else {
				top.forEach(s => body.appendChild(renderRow(s)));
			}
			if (count) count.textContent = String(top.length);

			if (ind) {
				ind.classList.add('active');
				setTimeout(() => ind.classList.remove('active'), 500);
			}
		} catch (e) {
			// Silent fail; next tick retries
		}
	}

	function init() {
		pollOnce();
		setInterval(pollOnce, POLL_MS);
	}

	if (document.readyState === 'loading') {
		document.addEventListener('DOMContentLoaded', init);
	} else {
		init();
	}
})();
