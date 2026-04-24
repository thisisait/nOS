/* Wing — Timeline client behaviour.
 * - Filter chips (filter events in-place by data-kind).
 * - Infinite scroll / Load-more against /api/v1/events?cursor=<>.
 */
(function () {
	'use strict';

	const API = '/api/v1';

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

	// ── Filter chips ──
	function initFilters() {
		const chips = document.querySelectorAll('.tl-chip');
		if (chips.length === 0) return;
		let active = 'all';

		chips.forEach(chip => {
			chip.addEventListener('click', function () {
				chips.forEach(c => c.classList.remove('active'));
				this.classList.add('active');
				active = this.dataset.filter;
				applyFilter(active);
			});
		});

		function applyFilter(kind) {
			const rows = document.querySelectorAll('.tl-event');
			rows.forEach(r => {
				if (kind === 'all') {
					r.style.display = '';
				} else {
					r.style.display = (r.dataset.kind === kind) ? '' : 'none';
				}
			});
			// Hide run headers whose only children are filtered out
			const runHdrs = document.querySelectorAll('.tl-run-header');
			runHdrs.forEach(h => {
				let sib = h.nextElementSibling;
				let visible = false;
				while (sib && !sib.classList.contains('tl-run-header')) {
					if (sib.classList.contains('tl-event') && sib.style.display !== 'none') {
						visible = true; break;
					}
					sib = sib.nextElementSibling;
				}
				h.style.display = visible ? '' : 'none';
			});
		}
	}

	// ── Event row builder (mirror of Latte markup) ──
	function kindFor(type) {
		if (!type) return 'ok';
		if (type.includes('migration'))   return 'migration';
		if (type.includes('upgrade'))     return 'upgrade';
		if (type.includes('coexistence')) return 'coexistence';
		if (type.includes('failed') || type.includes('unreachable')) return 'failed';
		if (type.includes('changed')) return 'changed';
		if (type.includes('start'))   return 'start';
		return 'ok';
	}

	function renderEvent(ev) {
		const kind = kindFor(ev.type);
		const row = el('div', { className: 'tl-event', 'data-kind': kind, 'data-type': ev.type, 'data-run-id': ev.run_id || '' });
		row.appendChild(el('span', { className: 'tl-event-ts' }, ev.ts || ''));

		const body = el('div', { className: 'tl-event-body' });
		const head = el('div', { className: 'tl-event-head' });
		head.appendChild(el('span', { className: 'tl-event-type kind-' + kind }, ev.type || ''));

		let mainText = ev.task || '';
		if (!mainText && ev.migration_id) {
			const a = el('a', { href: '/migrations/' + ev.migration_id }, ev.migration_id);
			const wrap = el('span', { className: 'tl-event-task' }, a);
			head.appendChild(wrap);
		} else if (mainText) {
			head.appendChild(el('span', { className: 'tl-event-task' }, mainText));
		}
		body.appendChild(head);

		const meta = el('div', { className: 'tl-event-meta' });
		if (ev.role) meta.appendChild(el('span', null, 'role: ', el('code', null, ev.role)));
		if (ev.host) meta.appendChild(el('span', null, 'host: ', el('code', null, ev.host)));
		if (ev.duration_ms) meta.appendChild(el('span', null, ev.duration_ms + 'ms'));
		if (ev.coexistence_service) meta.appendChild(el('span', null, 'svc: ', el('code', null, ev.coexistence_service)));
		body.appendChild(meta);

		row.appendChild(body);
		return row;
	}

	// ── Load-more / infinite scroll ──
	function initLoadMore() {
		const btn = document.getElementById('tl-loadmore');
		const stream = document.getElementById('tl-stream');
		if (!btn || !stream) return;

		let cursor = btn.dataset.cursor;
		let loading = false;

		async function loadMore() {
			if (loading || !cursor) return;
			loading = true;
			btn.disabled = true;
			const origLabel = btn.textContent;
			btn.textContent = '';
			btn.appendChild(el('span', { className: 'tl-spinner', 'aria-hidden': 'true' }));
			btn.appendChild(document.createTextNode('Loading…'));

			try {
				const res = await fetch(`${API}/events?cursor=${encodeURIComponent(cursor)}&limit=50`);
				if (!res.ok) throw new Error('HTTP ' + res.status);
				const data = await res.json();
				const events = Array.isArray(data) ? data : (data.events || []);

				let lastRun = null;
				// Find last run header already in stream to avoid duplicating
				const existingRuns = stream.querySelectorAll('.tl-event');
				if (existingRuns.length) lastRun = existingRuns[existingRuns.length - 1].dataset.runId;

				events.forEach(ev => {
					if (ev.run_id && ev.run_id !== lastRun) {
						const hdr = el('div', { className: 'tl-run-header' },
							el('span', null, 'Run'),
							el('span', { className: 'run-id' }, ev.run_id)
						);
						stream.appendChild(hdr);
						lastRun = ev.run_id;
					}
					stream.appendChild(renderEvent(ev));
				});

				cursor = data.next_cursor || null;
				if (cursor) {
					btn.dataset.cursor = cursor;
					btn.textContent = origLabel;
					btn.disabled = false;
				} else {
					btn.textContent = 'All caught up';
					// Stay disabled
				}
			} catch (err) {
				btn.textContent = 'Retry (' + err.message + ')';
				btn.disabled = false;
			} finally {
				loading = false;
			}
		}

		btn.addEventListener('click', loadMore);

		// IntersectionObserver for auto-load when button scrolls into view
		if ('IntersectionObserver' in window) {
			const io = new IntersectionObserver(entries => {
				entries.forEach(entry => {
					if (entry.isIntersecting && cursor && !loading) loadMore();
				});
			}, { rootMargin: '400px' });
			io.observe(btn);
		}
	}

	function init() {
		initFilters();
		initLoadMore();
	}

	if (document.readyState === 'loading') {
		document.addEventListener('DOMContentLoaded', init);
	} else {
		init();
	}
})();
