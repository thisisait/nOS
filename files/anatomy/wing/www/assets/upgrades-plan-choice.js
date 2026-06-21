/* Wing — Plan-choice modal (B4b).
 *
 * Sits between the "Plan" click and the queue write on /upgrades + /upgrades/<svc>.
 * The operator picks (a) Migration in-place (default) or (b) Coexisting new version
 * with a data copy. Option (b) is enabled only when the triggering control declares
 * data-coexist-supported="1". The flag flows truthfully from the recipe both on the
 * /upgrades matrix (upgrade_recipes.coexistence_supported, ingested from the recipe
 * YAML — F1) and on /upgrades/<svc> (BoxAPI recipes carry coexistence_supported).
 *
 * Vanilla data-action delegation — same pattern as migrations.js /
 * widget-cutover-confirm.js. NO fetch: submit-plan-choice sets the hidden inputs and
 * submits the real CSRF <form>, so the server-side redirect + flash UX is preserved.
 *
 * Phase 2 (upgrade-reset-scope-and-session-safety): the trigger button also carries
 * the recipe's reset SCOPE via data-* — data-session-risk, data-reset-scope,
 * data-estimated-sec, data-affected-services, data-affected-host-apps,
 * data-reset-reason. open() renders a human "disruption preview" badge from those
 * and, when data-session-risk="1" (scope host_app / host_reboot), unhides a warning
 * callout + a run_mode radio group (Detached default / Attached, plus "Stage, then
 * reboot" only for host_reboot). The hidden run_mode input is synced from the radio
 * before submit; non-session-risk recipes leave it 'attached' (posted implicitly).
 */
(function () {
	'use strict';

	const modal = {
		root: null, form: null, svcLabel: null, recipeLabel: null,
		modeInput: null, targetInput: null, portInput: null, dataCopyInput: null,
		coexistLabel: null, coexistRadio: null, coexistNa: null,
		runModeInput: null, runModeFieldset: null, stageLabel: null,
		disruptionBadge: null, disruptionDetail: null, sessionWarning: null,
		service: null, recipe: null, lastFocus: null,

		ensure() {
			this.root = document.getElementById('plan-choice-modal');
			this.form = document.getElementById('plan-choice-form');
			this.svcLabel = document.getElementById('plan-choice-svc');
			this.recipeLabel = document.getElementById('plan-choice-recipe');
			this.modeInput = document.getElementById('plan-choice-mode');
			this.targetInput = document.getElementById('plan-choice-target');
			this.portInput = document.getElementById('plan-choice-port');
			this.dataCopyInput = document.getElementById('plan-choice-datacopy');
			this.coexistLabel = document.getElementById('plan-choice-coexist-label');
			this.coexistRadio = document.getElementById('plan-choice-coexist-radio');
			this.coexistNa = this.coexistLabel ? this.coexistLabel.querySelector('.plan-choice-coexist-na') : null;
			this.runModeInput = document.getElementById('plan-choice-runmode');
			this.runModeFieldset = document.getElementById('plan-choice-runmode-fieldset');
			this.stageLabel = document.getElementById('plan-choice-runmode-stage-label');
			this.disruptionBadge = document.getElementById('plan-choice-disruption-badge');
			this.disruptionDetail = document.getElementById('plan-choice-disruption-detail');
			this.sessionWarning = document.getElementById('plan-choice-session-warning');
			return !!this.root && !!this.form;
		},

		open(btn) {
			if (!this.ensure()) return;
			const svc = btn.dataset.service || '';
			const recipe = btn.dataset.recipeId || '';
			const target = btn.dataset.target || '';
			const coexistSupported = btn.dataset.coexistSupported === '1';

			// Phase 2: the recipe's reset scope, threaded via data-* (mirrors the
			// data-coexist-supported channel — the partial is a static singleton).
			const sessionRisk = btn.dataset.sessionRisk === '1';
			const scope = btn.dataset.resetScope || 'container';
			const estimatedSec = btn.dataset.estimatedSec || '';
			const affectedServices = btn.dataset.affectedServices || '';
			const affectedHostApps = btn.dataset.affectedHostApps || '';
			const resetReason = btn.dataset.resetReason || '';

			this.service = svc;
			this.recipe = recipe;
			if (this.svcLabel) this.svcLabel.textContent = svc;
			if (this.recipeLabel) this.recipeLabel.textContent = recipe;
			if (this.targetInput) this.targetInput.value = target;

			// Browser route (wing is served at root): /upgrades/<svc>/<recipe>/plan-choice.
			this.form.action = '/upgrades/' + encodeURIComponent(svc) + '/' + encodeURIComponent(recipe) + '/plan-choice';

			// Reset to the default (a) Migration in-place choice every open.
			const radioA = this.form.querySelector('input[name="plan_choice_radio"][value="migration"]');
			if (radioA) radioA.checked = true;
			if (this.coexistRadio) this.coexistRadio.checked = false;

			// Gate option (b) on coexistence support.
			this.setCoexistSupported(coexistSupported);
			this.syncMode();

			// Render the disruption preview + gate the run_mode group on session risk.
			this.renderDisruption(scope, estimatedSec, affectedServices, affectedHostApps, resetReason);
			this.setSessionRisk(sessionRisk, scope);

			this.lastFocus = document.activeElement;
			this.root.hidden = false;
			document.addEventListener('keydown', onEsc);
			if (radioA) setTimeout(() => radioA.focus(), 0);
		},

		// Build a human label for a reset scope, e.g.
		//   container    → "Container restart"
		//   stack        → "Stack bounce — 3 services"
		//   host_app     → "Restarts a host app"
		//   host_reboot  → "Requires host reboot"
		scopeLabel(scope, affectedServices) {
			switch (scope) {
				case 'host_reboot': return 'Requires host reboot';
				case 'host_app':    return 'Restarts a host app';
				case 'stack': {
					const n = affectedServices
						? affectedServices.split(',').map(s => s.trim()).filter(Boolean).length
						: 0;
					return n > 0 ? ('Stack bounce — ' + n + (n === 1 ? ' service' : ' services')) : 'Stack bounce';
				}
				case 'none':        return 'No restart';
				default:            return 'Container restart';
			}
		},

		// "(~30s)" / "(~2 min)" from estimated_sec; empty string when unknown.
		estimateLabel(estimatedSec) {
			const sec = parseInt(estimatedSec, 10);
			if (!Number.isFinite(sec) || sec <= 0) return '';
			if (sec <= 90) return ' (~' + sec + 's)';
			return ' (~' + Math.round(sec / 60) + ' min)';
		},

		// Fill the badge (scope label + ~estimate) + the optional detail line
		// (affected services / host apps / reason).
		renderDisruption(scope, estimatedSec, affectedServices, affectedHostApps, resetReason) {
			if (this.disruptionBadge) {
				this.disruptionBadge.dataset.scope = scope;
				this.disruptionBadge.textContent = this.scopeLabel(scope, affectedServices) + this.estimateLabel(estimatedSec);
			}
			if (this.disruptionDetail) {
				const bits = [];
				if (affectedServices) bits.push('Services: ' + affectedServices);
				if (affectedHostApps) bits.push('Host apps: ' + affectedHostApps);
				if (resetReason) bits.push(resetReason);
				const detail = bits.join(' — ');
				this.disruptionDetail.textContent = detail;
				this.disruptionDetail.hidden = detail === '';
			}
		},

		// Show the warning callout + run_mode radios ONLY for session-risky scopes
		// (host_app / host_reboot). Non-session-risk recipes keep the run_mode input
		// at its 'attached' default, posted implicitly with no extra prompt. The
		// "Stage, then reboot" option appears only for a host_reboot scope.
		setSessionRisk(risk, scope) {
			if (this.sessionWarning) this.sessionWarning.hidden = !risk;
			if (this.runModeFieldset) this.runModeFieldset.hidden = !risk;
			if (this.stageLabel) {
				const stageOk = risk && scope === 'host_reboot';
				this.stageLabel.hidden = !stageOk;
				if (!stageOk) {
					const stageRadio = document.getElementById('plan-choice-runmode-stage');
					if (stageRadio) stageRadio.checked = false;
				}
			}
			// Default the run_mode every open: detached (recommended) when risky,
			// else attached (the implicit, no-prompt default).
			const detached = document.getElementById('plan-choice-runmode-detached');
			const attached = this.form.querySelector('input[name="plan_runmode_radio"][value="attached"]');
			if (risk && detached) detached.checked = true;
			else if (!risk && attached) attached.checked = true;
			this.syncRunMode();
		},

		setCoexistSupported(supported) {
			if (!this.coexistLabel || !this.coexistRadio) return;
			this.coexistRadio.disabled = !supported;
			this.coexistLabel.setAttribute('data-disabled', supported ? 'false' : 'true');
			// Hover tooltip on the disabled option + the inline NA notice. Both
			// reflect the recipe's coexistence_supported (F1: flows from
			// upgrade_recipes.coexistence_supported on the matrix, the recipe YAML
			// on /upgrades/<svc>). Enabled → no tooltip, NA notice hidden.
			if (supported) {
				this.coexistLabel.removeAttribute('title');
			} else {
				this.coexistLabel.setAttribute('title', 'This recipe does not support coexistence');
			}
			if (this.coexistNa) this.coexistNa.hidden = supported;
			if (!supported && this.coexistRadio.checked) {
				this.coexistRadio.checked = false;
				const radioA = this.form.querySelector('input[name="plan_choice_radio"][value="migration"]');
				if (radioA) radioA.checked = true;
			}
		},

		// Reflect the chosen radio into the hidden plan_mode + data_copy inputs.
		syncMode() {
			const checked = this.form.querySelector('input[name="plan_choice_radio"]:checked');
			const mode = checked && checked.value === 'coexist' ? 'coexist' : 'migration';
			if (this.modeInput) this.modeInput.value = mode;
			// data_copy is only meaningful for (b); always 1 ("with a copy of the data").
			if (this.dataCopyInput) this.dataCopyInput.value = mode === 'coexist' ? '1' : '0';
		},

		// Reflect the chosen run_mode radio into the hidden run_mode input. When the
		// radio group is absent/hidden (non-session-risk recipe) the input keeps its
		// 'attached' default — the implicit, no-prompt posture.
		syncRunMode() {
			if (!this.runModeInput) return;
			if (this.runModeFieldset && this.runModeFieldset.hidden) {
				this.runModeInput.value = 'attached';
				return;
			}
			const checked = this.form.querySelector('input[name="plan_runmode_radio"]:checked');
			const allowed = { attached: 1, detached: 1, stage_then_reboot: 1 };
			this.runModeInput.value = checked && allowed[checked.value] ? checked.value : 'attached';
		},

		close() {
			if (!this.root) return;
			this.root.hidden = true;
			this.service = null;
			this.recipe = null;
			document.removeEventListener('keydown', onEsc);
			if (this.lastFocus && typeof this.lastFocus.focus === 'function') this.lastFocus.focus();
		},

		submit() {
			if (!this.form) return;
			this.syncMode();
			this.syncRunMode();
			this.form.submit();
		}
	};

	function onEsc(e) { if (e.key === 'Escape') modal.close(); }

	function init() {
		document.addEventListener('click', function (e) {
			const btn = e.target.closest('[data-action]');
			if (!btn) return;
			switch (btn.dataset.action) {
				case 'open-plan-choice':   e.preventDefault(); modal.open(btn); break;
				case 'close-plan-choice':  e.preventDefault(); modal.close(); break;
				case 'submit-plan-choice': e.preventDefault(); modal.submit(); break;
				case 'promote-to-migration': {
					// A3.2 (Q5): lightweight supervision gate for the native AgentKit
					// migration-author. NON-destructive (working-tree write + review MR,
					// makes nothing live), so a single window.confirm — not a typed
					// PRIMARY modal — is the right friction. On cancel, block the submit
					// of the CSRF <form> the button lives in; on confirm, let it through.
					const svc = btn.dataset.service || '';
					const recipe = btn.dataset.recipeId || '';
					const ok = window.confirm(
						'Promote ' + svc + '/' + recipe + ' to a migration record? This ' +
						'starts the migration-author agent (writes a migration YAML + ' +
						'version bump, opens a review MR). Nothing goes live.'
					);
					if (!ok) { e.preventDefault(); }
					break;
				}
			}
		});

		if (modal.ensure()) {
			// Keep the hidden plan_mode + run_mode in sync as the operator flips a radio.
			modal.form.addEventListener('change', function (e) {
				if (!e.target) return;
				if (e.target.name === 'plan_choice_radio') modal.syncMode();
				if (e.target.name === 'plan_runmode_radio') modal.syncRunMode();
			});
			// Backdrop click closes.
			modal.root.addEventListener('click', function (e) {
				if (e.target === modal.root) modal.close();
			});
		}
	}

	if (document.readyState === 'loading') {
		document.addEventListener('DOMContentLoaded', init);
	} else {
		init();
	}
})();
