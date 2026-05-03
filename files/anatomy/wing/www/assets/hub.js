/**
 * Wing Hub — systems dashboard client-side logic.
 *   - Stack/search filtering
 *   - Health probe polling via /api/v1/hub/health
 */
(function () {
	'use strict';

	const searchInput = document.getElementById('hub-search');
	const filterBtns = document.querySelectorAll('.filter-btn[data-filter]');
	const probeBtn = document.getElementById('hub-probe-all');
	const cards = () => Array.from(document.querySelectorAll('.sys-card'));
	const stacks = () => Array.from(document.querySelectorAll('.hub-stack'));

	let activeStack = 'all';
	let query = '';

	function applyFilter() {
		cards().forEach(card => {
			const stack = card.dataset.stack || '';
			const name = card.dataset.name || '';
			const cat = card.dataset.category || '';
			const stackOk = activeStack === 'all' || stack === activeStack;
			const queryOk = !query || name.includes(query) || cat.includes(query) || stack.includes(query);
			card.classList.toggle('hidden', !(stackOk && queryOk));
		});
		stacks().forEach(section => {
			const stackName = section.dataset.stack;
			const stackOk = activeStack === 'all' || stackName === activeStack;
			if (!stackOk) {
				section.classList.add('hidden');
			} else {
				section.classList.remove('hidden');
				// Hide section if all its cards are hidden
				const visibleCards = section.querySelectorAll('.sys-card:not(.hidden)');
				section.classList.toggle('hidden', visibleCards.length === 0);
			}
		});
	}

	filterBtns.forEach(btn => {
		btn.addEventListener('click', () => {
			filterBtns.forEach(b => b.classList.remove('active'));
			btn.classList.add('active');
			activeStack = btn.dataset.filter;
			applyFilter();
		});
	});

	if (searchInput) {
		searchInput.addEventListener('input', (ev) => {
			query = (ev.target.value || '').toLowerCase().trim();
			applyFilter();
		});
	}

	// Health polling
	async function probeHealth() {
		try {
			const res = await fetch('/api/v1/hub/health', { headers: { Accept: 'application/json' } });
			if (!res.ok) return;
			const data = await res.json();
			const probes = data.probes || [];
			const byId = Object.create(null);
			probes.forEach(p => { byId[p.id] = p; });

			cards().forEach(card => {
				const id = card.dataset.id;
				const probe = byId[id];
				if (!probe) return;

				card.dataset.health = probe.status;
				const dot = card.querySelector('.sys-health-dot');
				if (dot) {
					dot.className = 'sys-health-dot sys-health-' + probe.status;
					dot.title = probe.status + (probe.ms ? ' (' + probe.ms + 'ms)' : '');
				}
			});

			// Update stats
			const upCount = probes.filter(p => p.status === 'up').length;
			const downCount = probes.filter(p => p.status === 'down').length;
			const statValues = document.querySelectorAll('.stat .value');
			if (statValues[1]) statValues[1].textContent = upCount;
			if (statValues[2]) statValues[2].textContent = downCount;
		} catch (err) {
			console.warn('[hub] health probe failed:', err);
		}
	}

	if (probeBtn) {
		probeBtn.addEventListener('click', (ev) => {
			ev.preventDefault();
			probeBtn.textContent = 'Probing...';
			probeHealth().finally(() => { probeBtn.textContent = 'Probe All'; });
		});
	}

	// Initial probe + 30s interval
	probeHealth();
	setInterval(probeHealth, 30_000);
})();
