// Wing /users/created — copy-to-clipboard for the freshly-minted
// invitation URL. Extracted from inline <script> per W3 UI-hygiene gate
// (no inline <script> blocks in templates).

(function () {
	'use strict';

	function flash(btn, message, ms) {
		var original = btn.textContent;
		btn.textContent = message;
		setTimeout(function () { btn.textContent = original; }, ms);
	}

	function bind(btn) {
		btn.addEventListener('click', function () {
			var el = document.getElementById('inviteUrl');
			if (!el) {
				return;
			}
			el.select();
			el.setSelectionRange(0, 99999);
			if (navigator.clipboard && navigator.clipboard.writeText) {
				navigator.clipboard.writeText(el.value).then(
					function () { flash(btn, 'Copied!', 1800); },
					function () { flash(btn, 'Copy failed', 1800); }
				);
			} else {
				try {
					document.execCommand('copy');
					flash(btn, 'Copied!', 1800);
				} catch (e) {
					flash(btn, 'Copy failed', 1800);
				}
			}
		});
	}

	document.addEventListener('DOMContentLoaded', function () {
		var btns = document.querySelectorAll('[data-action="copy-invite-url"]');
		Array.prototype.forEach.call(btns, bind);
	});
})();
