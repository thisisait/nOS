// Inbox client-side filters: severity buttons + search input.
// Extracted from app/Templates/Inbox/default.latte during W3 cleanup
// (Anatomy 2026-05-17). Pure DOM scripting — no build step.
(function () {
	const rows = document.querySelectorAll('#inboxBody tr');

	document.querySelectorAll('[data-filter="severity"]').forEach(btn => {
		btn.addEventListener('click', () => {
			document.querySelectorAll('[data-filter="severity"]').forEach(b => b.classList.remove('active'));
			btn.classList.add('active');
			const val = btn.dataset.value;
			rows.forEach(r => {
				r.style.display = (!val || r.dataset.severity === val) ? '' : 'none';
			});
		});
	});

	const search = document.getElementById('inboxSearch');
	if (search) {
		search.addEventListener('input', () => {
			const q = search.value.toLowerCase();
			rows.forEach(r => {
				r.style.display = (r.dataset.search || '').includes(q) ? '' : 'none';
			});
		});
	}
})();
