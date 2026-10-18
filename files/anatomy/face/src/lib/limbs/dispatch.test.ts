import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import { windows, _reset } from '$lib/stores/desktop';
import { tiling, clearTiling } from '$lib/wm/tiling';
import {
	_resetRegistry,
	registerBuiltinNativeApps,
	registerNativeApp
} from '$lib/apps/native/registry';
import { declaredLimbs, dispatch } from './dispatch';

const act = (action: string, params: Record<string, unknown>, app = 'desktop') => ({
	act: `a-${action}`,
	app,
	action,
	params
});

beforeEach(() => {
	_reset();
	_resetRegistry();
	clearTiling();
	registerBuiltinNativeApps();
});

describe('limbs · desktop', () => {
	it('open_app tables leaves a tables window and answers ok', async () => {
		const r = await dispatch(act('open_app', { slug: 'tables' }));
		expect(r).toMatchObject({ act: 'a-open_app', ok: true });
		expect(get(windows).map((w) => w.app)).toEqual(['tables']);
	});

	it('a second open_app focuses, it does not duplicate', async () => {
		await dispatch(act('open_app', { slug: 'tables' }));
		await dispatch(act('open_app', { slug: 'files' }));
		const r = await dispatch(act('open_app', { slug: 'tables' }));
		expect(r.ok).toBe(true);
		const list = get(windows);
		expect(list.filter((w) => w.app === 'tables')).toHaveLength(1);
		const top = list.reduce((a, b) => (b.z > a.z ? b : a));
		expect(top.app).toBe('tables');
	});

	it('focus_window and close_window act on the app window', async () => {
		await dispatch(act('open_app', { slug: 'tables' }));
		await dispatch(act('open_app', { slug: 'files' }));
		expect((await dispatch(act('focus_window', { app: 'tables' }))).ok).toBe(true);
		expect((await dispatch(act('close_window', { app: 'tables' }))).ok).toBe(true);
		expect(get(windows).map((w) => w.app)).toEqual(['files']);
		expect((await dispatch(act('focus_window', { app: 'tables' }))).ok).toBe(false);
	});

	it('an undeclared action answers ok:false and changes nothing', async () => {
		await dispatch(act('open_app', { slug: 'tables' }));
		const before = get(windows);
		for (const a of [
			act('nuke', {}),
			act('open_app', { slug: 'x' }, 'tables'),
			act('toString', {})
		]) {
			const r = await dispatch(a);
			expect(r.ok).toBe(false);
			expect(r.reason).toBeTruthy();
		}
		expect(get(windows)).toEqual(before);
	});

	it('a bad param answers ok:false and changes nothing', async () => {
		const bad = [{ slug: 7 }, {}, { slug: 'tables', extra: 1 }, { mode: 'diagonal' }];
		for (const p of bad) {
			const r = await dispatch(act('mode' in p ? 'arrange' : 'open_app', p));
			expect(r.ok, JSON.stringify(p)).toBe(false);
		}
		expect(get(windows)).toEqual([]);
		expect(get(tiling).mode).toBeNull();
	});

	it('arrange 2x2 sets tiling.mode; arrange none clears it', async () => {
		await dispatch(act('open_app', { slug: 'tables' }));
		await dispatch(act('open_app', { slug: 'files' }));
		expect((await dispatch(act('arrange', { mode: '2x2' }))).ok).toBe(true);
		expect(get(tiling).mode).toBe('2x2');
		expect((await dispatch(act('arrange', { mode: 'none' }))).ok).toBe(true);
		expect(get(tiling).mode).toBeNull();
	});
});

describe('limbs · app-declared', () => {
	beforeEach(() => {
		registerNativeApp({
			slug: 'notes',
			title: 'Notes',
			icon: 'N',
			form: 'view',
			build: 'F1',
			component: async () => ({ default: (() => {}) as never }),
			limbs: [
				{
					action: 'rename',
					params: { name: { type: 'string', required: true } },
					writes: true,
					says: 'Rename a note',
					run: ({ name }) => `renamed ${name}`
				}
			]
		});
	});

	// The thalamus sends an Act for a write only after the card is approved.
	it('a writes:true limb runs when the Act arrives and answers ok', async () => {
		const r = await dispatch(act('rename', { name: 'x' }, 'notes'));
		expect(r).toEqual({ act: 'a-rename', ok: true, result: 'renamed x' });
	});

	it('declaredLimbs lists the desktop limbs and the app limb', () => {
		const names = declaredLimbs().map((l) => `${l.app}.${l.action}`);
		expect(names).toEqual(
			expect.arrayContaining([
				'desktop.open_app',
				'desktop.focus_window',
				'desktop.close_window',
				'desktop.arrange',
				'notes.rename'
			])
		);
		expect(declaredLimbs().every((l) => !('run' in l))).toBe(true);
	});
});
