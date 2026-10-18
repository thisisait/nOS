// genui I5i: the PoC workspace (state/fixtures/genui-workspace-poc/workspace.json) restores,
// runs its three widgets, and a write to expenses re-runs exactly the two that read it.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { route } from './widgets';
import { migrate, onTableChanged, restore, widgetsOf } from './workspace';

const POC = new URL(
	'../../../../../../state/fixtures/genui-workspace-poc/workspace.json',
	import.meta.url
);
// The PoC file is v2, as it was written: it loads as v3, as every v2 file does.
const layout = migrate(JSON.parse(readFileSync(POC, 'utf8')));

describe('the PoC workspace', () => {
	it('is one tab of a table, a chart and a form over expenses', () => {
		expect(layout.workspaces.length).toBe(1);
		expect(widgetsOf(layout.workspaces[0]).map((w) => Object.keys(w.spec)[0])).toEqual([
			'rows',
			'chart',
			'form'
		]);
	});

	it('restores by re-sending its three specs, and a write re-runs the two readers', () => {
		const boxes = widgetsOf(layout.workspaces[0]);
		const r = restore(layout);
		expect(r.send).toEqual(
			boxes.map((b) => ({ t: 'widget', widget: b.id, spec: b.spec, trigger: 'restore' }))
		);
		let w = r.w;
		for (const b of boxes)
			w = route(
				w,
				{
					t: 'widget',
					session: 's',
					widget: b.id,
					component: { kind: 'markdown', props: { text: '' } }
				},
				1
			)!;
		const after = onTableChanged(layout, w, 'expenses');
		const readers = boxes.filter((b) => !('form' in b.spec));
		expect(readers.length).toBe(2);
		expect(after.send, 'the form does not re-run').toEqual(
			readers.map((b) => ({ t: 'widget', widget: b.id, spec: b.spec, trigger: 'table_changed' }))
		);
		expect(onTableChanged(layout, w, 'notes').send, 'another table re-runs nothing').toEqual([]);
	});
});
