/** The desktop's own limbs — the WM's mutators, all writes:false (visible, undoable). */
import { get } from 'svelte/store';
import { windows, focusApp, closeWindow } from '$lib/stores/desktop';
import { openApp } from '$lib/apps/native/registry';
import { applyTiling, clearTiling, type TileMode } from '$lib/wm/tiling';
import type { LimbDecl } from './types';

export const DESKTOP = 'desktop';

function fail(reason: string): never {
	throw new Error(reason);
}

export const desktopLimbs: LimbDecl[] = [
	{
		action: 'open_app',
		params: { slug: { type: 'string', required: true } },
		writes: false,
		says: 'Open a face app, or bring its window to the front',
		run: ({ slug }) => openApp(slug as string) || fail(`cannot open ${slug}`)
	},
	{
		action: 'focus_window',
		params: { app: { type: 'string', required: true } },
		writes: false,
		says: "Bring an app's window to the front",
		run: ({ app }) => focusApp(app as string) || fail(`no window for ${app}`)
	},
	{
		action: 'close_window',
		params: { app: { type: 'string', required: true } },
		writes: false,
		says: "Close an app's front-most window",
		run: ({ app }) => {
			const mine = get(windows).filter((w) => w.app === app);
			if (!mine.length) fail(`no window for ${app}`);
			closeWindow(mine.reduce((a, b) => (b.z > a.z ? b : a)).id);
			return true;
		}
	},
	{
		action: 'arrange',
		params: {
			mode: { type: 'enum', values: ['half-v', 'thirds', '2x2', 'none'], required: true }
		},
		writes: false,
		says: 'Tile the front windows (half-v, thirds, 2x2) or stop tiling (none)',
		run: ({ mode }) => {
			if (mode === 'none') {
				clearTiling();
				return true;
			}
			return applyTiling(mode as TileMode) || fail('tiling needs two open windows');
		}
	}
];
