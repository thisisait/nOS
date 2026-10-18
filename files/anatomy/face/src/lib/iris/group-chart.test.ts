// @vitest-environment happy-dom
// Live 2026-10-18: the grouped table was right and the model's chart was refused twice. "Graf" draws a bar
// chart from that table's own rows, without the model, and it pins as a sourced show chart does.
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import Message from './Message.svelte';
import type { ToShell } from './wire';

const grouped: ToShell = {
	t: 'render',
	session: '0b6f6a1e-3c2d-4e5f-8a9b-0c1d2e3f4a5b',
	component: {
		kind: 'table_results',
		props: {
			table: 'assay-stock-moves',
			name: 'assay-stock-moves',
			query: 'grouped by direction · sum of qty',
			matched: 40,
			total: 40,
			columns: ['direction', 'count', 'sum'],
			projected: false,
			rows: [
				{ __id: 'out', cells: { direction: 'out', count: 20, sum: 422 } },
				{ __id: 'in', cells: { direction: 'in', count: 20, sum: 406 } }
			]
		}
	},
	pin: { rows: { table: 'assay-stock-moves', group_by: 'direction', op: 'sum', y: 'qty' } }
};

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
	if (app) unmount(app);
	app = null;
	document.body.replaceChildren();
});

describe('a grouped result draws its own chart', () => {
	it('"Graf" draws a bar chart of the groups, and it pins from the same query', () => {
		const pinned: [ToShell, boolean][] = [];
		app = mount(Message, {
			target: document.body,
			props: { msg: grouped, onpin: (m: ToShell, fresh: boolean) => pinned.push([m, fresh]) }
		});
		const button = (label: string) =>
			[...document.querySelectorAll('button')].filter((b) => b.textContent?.trim() === label);
		expect(document.querySelector('.chart svg')).toBeNull();
		expect(button('Graf')).toHaveLength(1);
		button('Graf')[0].click();
		flushSync();
		expect(document.querySelector('.chart svg'), 'a chart is drawn').not.toBeNull();
		expect(button('Graf'), 'drawn once').toHaveLength(0);
		expect(button('Sem')).toHaveLength(2);
		expect(button('Nová plocha')).toHaveLength(2);
		button('Nová plocha')[1].click();
		expect(pinned).toHaveLength(1);
		const [m, fresh] = pinned[0];
		expect(fresh).toBe(true);
		expect(m.t === 'render' && m.pin).toEqual({
			chart: {
				query: { table: 'assay-stock-moves' },
				chart: 'bar',
				x: 'direction',
				y: 'qty',
				op: 'sum'
			}
		});
		expect(m.t === 'render' && m.component).toMatchObject({
			kind: 'chart',
			props: {
				chart: 'bar',
				x: 'category',
				series: [
					{
						points: [
							['out', 422],
							['in', 406]
						]
					}
				]
			}
		});
	});
});
