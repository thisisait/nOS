// Wing burger-toggled fullscreen navigation overlay (W5, 2026-05-26).
//
// The horizontal tab bar was replaced by a fullscreen overlay opened from a
// burger button in the header (operator request). This wires the toggle:
//   - burger click            → open
//   - close button / ESC      → close
//   - click a nav link        → close (navigation reloads anyway; closing
//                               first avoids a flash of the overlay on the
//                               next page if the browser restores scroll)
//   - body scroll is locked while open (.nav-open)
//
// Accessibility: aria-expanded reflects state, focus moves to the close
// button on open and back to the burger on close, ESC closes.
(function () {
	const burger = document.getElementById('navBurger');
	const overlay = document.getElementById('navOverlay');
	const closeBtn = document.getElementById('navClose');
	if (!burger || !overlay || !closeBtn) return;

	function open() {
		overlay.hidden = false;
		document.body.classList.add('nav-open');
		burger.setAttribute('aria-expanded', 'true');
		closeBtn.focus();
	}

	function close() {
		overlay.hidden = true;
		document.body.classList.remove('nav-open');
		burger.setAttribute('aria-expanded', 'false');
		burger.focus();
	}

	burger.addEventListener('click', open);
	closeBtn.addEventListener('click', close);

	// Close when a navigation link is activated.
	overlay.addEventListener('click', (e) => {
		const link = e.target.closest('a.tab');
		if (link) close();
	});

	// ESC closes while the overlay is open.
	document.addEventListener('keydown', (e) => {
		if (e.key === 'Escape' && !overlay.hidden) {
			e.preventDefault();
			close();
		}
	});
})();
