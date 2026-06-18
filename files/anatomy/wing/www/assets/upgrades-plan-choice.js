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
 */
(function () {
	'use strict';

	const modal = {
		root: null, form: null, svcLabel: null, recipeLabel: null,
		modeInput: null, targetInput: null, portInput: null, dataCopyInput: null,
		coexistLabel: null, coexistRadio: null, coexistNa: null,
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
			return !!this.root && !!this.form;
		},

		open(btn) {
			if (!this.ensure()) return;
			const svc = btn.dataset.service || '';
			const recipe = btn.dataset.recipeId || '';
			const target = btn.dataset.target || '';
			const coexistSupported = btn.dataset.coexistSupported === '1';

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

			this.lastFocus = document.activeElement;
			this.root.hidden = false;
			document.addEventListener('keydown', onEsc);
			if (radioA) setTimeout(() => radioA.focus(), 0);
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
			// Keep the hidden plan_mode in sync as the operator flips the radio.
			modal.form.addEventListener('change', function (e) {
				if (e.target && e.target.name === 'plan_choice_radio') modal.syncMode();
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
