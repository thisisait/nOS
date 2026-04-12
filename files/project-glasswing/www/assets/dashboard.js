/* Glasswing Dashboard — client-side interactivity */
(function () {
	'use strict';

	const API = '/api/v1';

	// ── Safe DOM helpers (avoid innerHTML for untrusted data) ──
	function el(tag, attrs, ...children) {
		const node = document.createElement(tag);
		if (attrs) Object.entries(attrs).forEach(([k, v]) => {
			if (k === 'style' && typeof v === 'string') node.setAttribute('style', v);
			else if (k === 'className') node.className = v;
			else node.setAttribute(k, v);
		});
		children.forEach(c => {
			if (typeof c === 'string') node.appendChild(document.createTextNode(c));
			else if (c) node.appendChild(c);
		});
		return node;
	}

	// ── Tab switching (for Dashboard sub-tabs: overview/timeline/components) ──
	function initTabs() {
		const tabs = document.querySelectorAll('.tab-content');
		const tabLinks = document.querySelectorAll('#tabs .tab');

		function activateHash() {
			const hash = location.hash.replace('#', '') || 'overview';
			tabs.forEach(t => t.classList.toggle('active', t.id === 'tab-' + hash));
			tabLinks.forEach(l => {
				const tabName = l.dataset.tab;
				l.classList.toggle('active', tabName === hash);
			});
		}

		if (tabs.length > 0) {
			window.addEventListener('hashchange', activateHash);
			activateHash();
		}
	}

	// ── Keyboard shortcuts ──
	document.addEventListener('keydown', function (e) {
		if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
		const routes = { '1': '/', '2': '/#timeline', '3': '/#components', '4': '/pentest', '5': '/remediation', '6': '/help' };
		if (routes[e.key]) {
			e.preventDefault();
			location.href = routes[e.key];
		}
	});

	// ── Header status (auto-refresh from API) ──
	async function loadStatus() {
		try {
			const res = await fetch(API + '/dashboard/summary');
			const data = await res.json();
			const container = document.getElementById('headerStatus');
			if (!container) return;
			container.textContent = '';

			const pill = el('span', { className: 'status-pill', style: data.remediation?.critical_pending > 0
				? 'background:rgba(248,81,73,0.15);color:var(--red)'
				: 'background:rgba(63,185,80,0.1);color:var(--green)' },
				el('span', { className: 'pulse', style: data.remediation?.critical_pending > 0
					? 'background:var(--red)' : 'background:var(--green)' }),
				data.remediation?.critical_pending > 0
					? data.remediation.critical_pending + ' CRITICAL'
					: 'Nominal'
			);
			container.appendChild(pill);
			container.appendChild(el('span', { style: 'color:var(--text2);font-size:12px' }, 'Cycle ' + (data.scan_cycle ?? '?')));
		} catch (e) {
			// API not available
		}
	}

	// ── Remediation filters ──
	function initRemediationFilters() {
		const table = document.getElementById('remTable');
		if (!table) return;

		const filterBtns = document.querySelectorAll('.filter-btn');
		const searchInput = document.getElementById('remSearch');
		let activeFilters = { status: '', severity: '' };

		filterBtns.forEach(btn => {
			btn.addEventListener('click', function () {
				const filterType = this.dataset.filter;
				filterBtns.forEach(b => {
					if (b.dataset.filter === filterType) b.classList.remove('active');
				});
				this.classList.add('active');
				activeFilters[filterType] = this.dataset.value;
				applyFilters();
			});
		});

		if (searchInput) {
			searchInput.addEventListener('input', applyFilters);
		}

		function applyFilters() {
			const searchTerm = (searchInput?.value || '').toLowerCase();
			const rows = document.querySelectorAll('#remBody tr');
			rows.forEach(row => {
				const matchStatus = !activeFilters.status || row.dataset.status === activeFilters.status;
				const matchSeverity = !activeFilters.severity || row.dataset.severity === activeFilters.severity;
				const matchSearch = !searchTerm || (row.dataset.search || '').includes(searchTerm);
				row.style.display = (matchStatus && matchSeverity && matchSearch) ? '' : 'none';
			});
		}
	}

	// ── Table sorting ──
	function initTableSort() {
		const headers = document.querySelectorAll('.rem-table th[data-sort]');
		let currentSort = { col: null, asc: true };

		headers.forEach(th => {
			th.addEventListener('click', function () {
				const col = this.dataset.sort;
				currentSort.asc = currentSort.col === col ? !currentSort.asc : true;
				currentSort.col = col;

				const tbody = document.getElementById('remBody');
				const rows = Array.from(tbody.querySelectorAll('tr'));
				const colIndex = Array.from(this.parentElement.children).indexOf(this);

				rows.sort((a, b) => {
					const aVal = a.children[colIndex]?.textContent.trim() || '';
					const bVal = b.children[colIndex]?.textContent.trim() || '';
					return currentSort.asc ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
				});

				rows.forEach(r => tbody.appendChild(r));
				headers.forEach(h => {
					const arrow = h.querySelector('.sort-arrow');
					if (arrow) arrow.textContent = h === this ? (currentSort.asc ? '\u25B2' : '\u25BC') : '';
				});
			});
		});
	}

	// ── Pentest target detail loading (lazy, safe DOM construction) ──
	function initPentestLazy() {
		document.querySelectorAll('.card-header').forEach(header => {
			header.addEventListener('click', function () {
				const body = this.nextElementSibling;
				if (!body) return;

				body.querySelectorAll('.target-areas[data-target]').forEach(async (container) => {
					if (container.dataset.loaded) return;
					container.dataset.loaded = '1';

					const targetId = container.dataset.target;
					try {
						const res = await fetch(API + '/pentest/targets/' + encodeURIComponent(targetId));
						const data = await res.json();
						container.textContent = '';

						const areas = container.dataset.type === 'tested' ? (data.areas_tested || []) : (data.areas_planned || []);
						if (areas.length === 0) {
							container.appendChild(el('div', { style: 'color:var(--text2);font-size:13px' }, 'None'));
							return;
						}

						areas.forEach(a => {
							if (container.dataset.type === 'tested') {
								const dotClass = a.result === 'no_findings' ? 'dot-tested' : 'dot-finding';
								container.appendChild(el('div', { className: 'pentest-area' },
									el('span', { className: 'dot ' + dotClass }),
									el('strong', null, a.area || ''),
									el('span', { style: 'color:var(--text2);margin-left:auto;font-size:12px' }, a.date || '')
								));
							} else {
								container.appendChild(el('div', { className: 'pentest-area' },
									el('span', { className: 'dot dot-planned' }),
									document.createTextNode(a.area || ''),
									el('span', { className: 'badge badge-' + (a.priority || 'medium'), style: 'margin-left:8px' }, a.priority || 'medium')
								));
							}
						});
					} catch (e) {
						container.textContent = '';
						container.appendChild(el('div', { style: 'color:var(--red);font-size:13px' }, 'Failed to load'));
					}
				});
			});
		});
	}

	// ── Init ──
	document.addEventListener('DOMContentLoaded', function () {
		initTabs();
		loadStatus();
		initRemediationFilters();
		initTableSort();
		initPentestLazy();
	});
})();
