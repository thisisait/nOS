/* Wing — Migrations UI
 *
 * Handles [Preview], [Apply], [Rollback] buttons on both /migrations and
 * /migrations/<id>. Uses the shared Preview modal to show a dry-run plan
 * before confirming an apply.
 *
 * Wired exclusively through data-action attributes — no inline handlers.
 * Matches the vanilla pattern in dashboard.js.
 */
(function () {
	'use strict';

	const API = '/api/v1';

	// ── Safe DOM helpers (mirrors dashboard.js) ──
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

	function setBusy(btn, busy) {
		if (!btn) return;
		btn.disabled = !!busy;
		if (busy) btn.dataset.prevLabel = btn.textContent;
		btn.textContent = busy ? 'Working…' : (btn.dataset.prevLabel || btn.textContent);
	}

	async function apiGet(path) {
		const res = await fetch(API + path, { headers: { 'Accept': 'application/json' } });
		if (!res.ok) throw new Error('HTTP ' + res.status);
		return res.json();
	}

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

	// ── Preview modal ──
	const modal = {
		root: null, body: null, applyBtn: null, currentId: null, currentSev: null,

		ensure() {
			this.root = document.getElementById('mig-preview-modal');
			this.body = document.getElementById('mig-preview-body');
			this.applyBtn = document.getElementById('mig-preview-apply');
			return !!this.root;
		},

		open(migrationId, severity) {
			if (!this.ensure()) return;
			this.currentId = migrationId;
			this.currentSev = severity;
			this.body.textContent = 'Loading preview…';
			this.applyBtn.disabled = true;
			this.root.hidden = false;
			document.addEventListener('keydown', onEsc);
			// Focus trap: focus the Close button first
			const closeBtn = this.root.querySelector('[data-action="close-preview"]');
			if (closeBtn) closeBtn.focus();
		},

		close() {
			if (!this.root) return;
			this.root.hidden = true;
			this.currentId = null;
			this.currentSev = null;
			document.removeEventListener('keydown', onEsc);
		},

		renderPlan(data) {
			this.body.textContent = '';
			const lines = [];
			if (Array.isArray(data.plan)) {
				data.plan.forEach(step => {
					lines.push(`[${step.status || 'pending'}] ${step.id}`);
					if (step.action && step.action.type) lines.push(`    ${step.action.type}`);
					if (step.description)                 lines.push(`    ${step.description}`);
				});
			} else if (typeof data === 'string') {
				lines.push(data);
			} else {
				lines.push(JSON.stringify(data, null, 2));
			}
			this.body.textContent = lines.join('\n');
			this.applyBtn.disabled = false;
		},

		renderError(msg) {
			this.body.textContent = '';
			this.body.appendChild(el('div', { style: 'color:var(--red)' }, 'Preview failed: ' + msg));
			this.applyBtn.disabled = true;
		}
	};

	function onEsc(e) { if (e.key === 'Escape') modal.close(); }

	// ── Handlers ──
	async function handlePreview(btn) {
		const id = btn.dataset.migrationId;
		const sev = btn.dataset.severity || 'minor';
		modal.open(id, sev);
		try {
			const data = await apiPost(`/migrations/${encodeURIComponent(id)}/preview`);
			modal.renderPlan(data);
		} catch (err) {
			modal.renderError(err.message);
		}
	}

	async function handleApply(btn) {
		const id = btn.dataset.migrationId;
		const sev = btn.dataset.severity || 'minor';

		// Breaking severity needs extra confirmation
		const msg = (sev === 'breaking' || sev === 'critical')
			? `Apply BREAKING migration "${id}"?\n\nThis may cause downtime. Make sure you've read the summary.`
			: `Apply migration "${id}"?`;
		if (!window.confirm(msg)) return;

		setBusy(btn, true);
		try {
			const res = await apiPost(`/migrations/${encodeURIComponent(id)}/apply`);
			if (res.success === false) {
				alert('Apply reported failure: ' + (res.error || 'unknown error'));
			}
			window.location.reload();
		} catch (err) {
			alert('Apply failed: ' + err.message);
			setBusy(btn, false);
		}
	}

	async function handleRollback(btn) {
		const id = btn.dataset.migrationId;
		if (!window.confirm(`Roll back migration "${id}"?\n\nAll declared inverse actions will run.`)) return;
		setBusy(btn, true);
		try {
			const res = await apiPost(`/migrations/${encodeURIComponent(id)}/rollback`);
			if (res.success === false) {
				alert('Rollback reported failure: ' + (res.error || 'unknown error'));
			}
			window.location.reload();
		} catch (err) {
			alert('Rollback failed: ' + err.message);
			setBusy(btn, false);
		}
	}

	async function handlePlanUpgrade(btn) {
		const svc = btn.dataset.service;
		const recipeId = btn.dataset.recipeId;
		modal.ensure();
		if (!modal.root) return;
		modal.open(recipeId, btn.dataset.severity);
		try {
			const data = await apiPost(`/upgrades/${encodeURIComponent(svc)}/${encodeURIComponent(recipeId)}/plan`);
			modal.renderPlan(data);
			// Swap the Apply button to trigger upgrade-apply
			modal.applyBtn.dataset.upgradeSvc = svc;
			modal.applyBtn.dataset.upgradeRecipe = recipeId;
			modal.applyBtn.dataset.mode = 'upgrade';
		} catch (err) {
			modal.renderError(err.message);
		}
	}

	async function handleApplyUpgrade(btn) {
		const svc = btn.dataset.service;
		const recipeId = btn.dataset.recipeId;
		const sev = btn.dataset.severity || 'minor';
		const msg = (sev === 'breaking' || sev === 'critical')
			? `Apply BREAKING upgrade ${svc} → ${recipeId}?\n\nConsider running [Plan] first and verifying the preview.`
			: `Apply upgrade ${svc} → ${recipeId}?`;
		if (!window.confirm(msg)) return;

		setBusy(btn, true);
		try {
			const res = await apiPost(`/upgrades/${encodeURIComponent(svc)}/${encodeURIComponent(recipeId)}/apply`);
			if (res.success === false) {
				alert('Upgrade reported failure: ' + (res.error || 'unknown error'));
			}
			window.location.reload();
		} catch (err) {
			alert('Upgrade failed: ' + err.message);
			setBusy(btn, false);
		}
	}

	async function handleRollbackUpgrade(btn) {
		const svc = btn.dataset.service;
		const recipeId = btn.dataset.recipeId;
		if (!window.confirm(`Roll back upgrade ${svc} / ${recipeId}?`)) return;
		setBusy(btn, true);
		try {
			await apiPost(`/upgrades/${encodeURIComponent(svc)}/${encodeURIComponent(recipeId)}/rollback`);
			window.location.reload();
		} catch (err) {
			alert('Rollback failed: ' + err.message);
			setBusy(btn, false);
		}
	}

	async function handleModalConfirmApply() {
		if (!modal.applyBtn) return;
		// Modal can confirm either a migration apply or an upgrade apply
		if (modal.applyBtn.dataset.mode === 'upgrade') {
			const svc = modal.applyBtn.dataset.upgradeSvc;
			const recipeId = modal.applyBtn.dataset.upgradeRecipe;
			setBusy(modal.applyBtn, true);
			try {
				await apiPost(`/upgrades/${encodeURIComponent(svc)}/${encodeURIComponent(recipeId)}/apply`);
				window.location.reload();
			} catch (err) {
				alert('Upgrade apply failed: ' + err.message);
				setBusy(modal.applyBtn, false);
			}
			return;
		}
		const id = modal.currentId;
		if (!id) return;
		const sev = modal.currentSev || 'minor';
		const msg = (sev === 'breaking' || sev === 'critical')
			? `Apply BREAKING migration "${id}"? This may cause downtime.`
			: `Apply migration "${id}"?`;
		if (!window.confirm(msg)) return;
		setBusy(modal.applyBtn, true);
		try {
			await apiPost(`/migrations/${encodeURIComponent(id)}/apply`);
			window.location.reload();
		} catch (err) {
			alert('Apply failed: ' + err.message);
			setBusy(modal.applyBtn, false);
		}
	}

	// ── Event delegation — one listener for the whole doc ──
	function init() {
		document.addEventListener('click', function (e) {
			const btn = e.target.closest('[data-action]');
			if (!btn) return;
			const action = btn.dataset.action;

			switch (action) {
				case 'preview':          e.preventDefault(); handlePreview(btn); break;
				case 'apply':            e.preventDefault(); handleApply(btn); break;
				case 'rollback':         e.preventDefault(); handleRollback(btn); break;
				case 'plan':             e.preventDefault(); handlePlanUpgrade(btn); break;
				case 'apply-upgrade':    e.preventDefault(); handleApplyUpgrade(btn); break;
				case 'rollback-upgrade': e.preventDefault(); handleRollbackUpgrade(btn); break;
				case 'close-preview':    e.preventDefault(); modal.close(); break;
				case 'confirm-apply':    e.preventDefault(); handleModalConfirmApply(); break;
			}
		});

		// Close modal on backdrop click
		const mb = document.getElementById('mig-preview-modal');
		if (mb) {
			mb.addEventListener('click', function (e) {
				if (e.target === mb) modal.close();
			});
		}
	}

	if (document.readyState === 'loading') {
		document.addEventListener('DOMContentLoaded', init);
	} else {
		init();
	}
})();
