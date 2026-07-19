import { describe, it, expect } from 'vitest';
import { toTableSummaries } from './summary';

describe('toTableSummaries', () => {
	it('unwraps the {success,data} envelope + maps id→slug', () => {
		const out = toTableSummaries({
			success: true,
			data: [
				{ id: 'face-wallpapers', title: 'Wallpapers', rowCount: 5 },
				{ id: 'face-layouts', title: 'Layouts', rowCount: 6 }
			]
		});
		expect(out).toEqual([
			{ slug: 'face-layouts', title: 'Layouts', rowCount: 6 },
			{ slug: 'face-wallpapers', title: 'Wallpapers', rowCount: 5 }
		]);
	});
	it('accepts a bare array + falls back title→slug, rowCount→0', () => {
		const out = toTableSummaries([{ slug: 'apps' }]);
		expect(out).toEqual([{ slug: 'apps', title: 'apps', rowCount: 0 }]);
	});
	it('drops entries with no id/slug/name and handles non-arrays', () => {
		expect(toTableSummaries([{ title: 'nokey' }, { id: 'ok' }])).toEqual([
			{ slug: 'ok', title: 'ok', rowCount: 0 }
		]);
		expect(toTableSummaries(null)).toEqual([]);
		expect(toTableSummaries({ nope: 1 })).toEqual([]);
	});
});
