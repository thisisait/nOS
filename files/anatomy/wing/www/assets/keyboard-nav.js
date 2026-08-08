// Wing top-nav keyboard navigation (W4, 2026-05-17).
//
// Pre-W4 the tab chips ("Hub 1", "Inbox 2", ...) suggested keyboard nav
// but no JS was wired. Wing operators reach for the keyboard a lot
// (inbox triage: mark-read, answering agent questions); this closes the
// loop. (Key 3 was the Approvals tab until A11's retirement, 2026-08-08 —
// it stays unassigned so the other digits keep their muscle memory.)
//
// Behavior:
//   - Press a digit (0-9) → navigate to the tab whose .tab-key chip
//     shows that digit.
//   - Ignored while the user is typing in an input/textarea/contenteditable
//     so search boxes + filter inputs keep their digit keys.
//   - No-op if no tab matches the pressed digit.
(function () {
	function isTyping(target) {
		if (!target) return false;
		const tag = (target.tagName || '').toLowerCase();
		if (tag === 'input' || tag === 'textarea' || tag === 'select') return true;
		if (target.isContentEditable) return true;
		return false;
	}

	function tabForDigit(digit) {
		const chips = document.querySelectorAll('.tab .tab-key');
		for (const chip of chips) {
			if ((chip.textContent || '').trim() === digit) {
				return chip.closest('.tab');
			}
		}
		return null;
	}

	document.addEventListener('keydown', (e) => {
		if (e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return;
		if (e.key.length !== 1 || e.key < '0' || e.key > '9') return;
		if (isTyping(e.target)) return;
		const tab = tabForDigit(e.key);
		if (tab && tab.href) {
			e.preventDefault();
			window.location.href = tab.href;
		}
	});
})();
