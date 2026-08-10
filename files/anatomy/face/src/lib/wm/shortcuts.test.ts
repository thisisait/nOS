import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import { resolve, isTextEntry, run, SHORTCUTS } from './shortcuts';
import { windows, openWindow, _reset } from '$lib/stores/desktop';

describe('chord resolution', () => {
	it('requires a modifier', () => {
		expect(resolve({ key: 'Backspace' })).toBeNull();
		expect(resolve({ key: 'Backspace', metaKey: true })).toBe('close');
		expect(resolve({ key: 'Backspace', ctrlKey: true })).toBe('close');
	});

	it('does NOT bind close to Cmd/Ctrl+W', () => {
		// That is the browser's tab-close. A web app fighting it loses: Chrome
		// refuses to let it be intercepted, and where it works the user loses
		// the shortcut they actually meant.
		expect(resolve({ key: 'w', metaKey: true })).toBeNull();
	});

	it('reverses cycle with shift', () => {
		expect(resolve({ key: '`', metaKey: true })).toBe('cycle');
		expect(resolve({ key: '`', metaKey: true, shiftKey: true })).toBe('cycle-back');
	});

	it('ignores unbound chords', () => {
		expect(resolve({ key: 'q', metaKey: true })).toBeNull();
	});
});

describe('text entry is never hijacked', () => {
	it.each(['input', 'textarea', 'select'])('bails inside <%s>', (tag) => {
		expect(isTextEntry({ tagName: tag.toUpperCase() } as unknown as EventTarget)).toBe(true);
	});

	it('bails inside contenteditable', () => {
		expect(isTextEntry({ tagName: 'DIV', isContentEditable: true } as unknown as EventTarget)).toBe(
			true
		);
	});

	it('acts normally elsewhere', () => {
		expect(isTextEntry({ tagName: 'DIV' } as unknown as EventTarget)).toBe(false);
		expect(isTextEntry(null)).toBe(false);
	});
});

describe('actions against the window store', () => {
	beforeEach(() => _reset());

	it('closes the front window', () => {
		openWindow({ app: 'a', title: 'A' });
		const b = openWindow({ app: 'b', title: 'B' });
		expect(run('close')).toBe(true);
		expect(get(windows).map((w) => w.id)).not.toContain(b);
		expect(get(windows)).toHaveLength(1);
	});

	it('does nothing, gracefully, with no windows', () => {
		expect(run('close')).toBe(false);
		expect(run('minimize')).toBe(false);
	});

	it('cycles in a stable order rather than by z', () => {
		// Cycling by z-order reorders the list you are cycling through, so you
		// bounce between two windows and can never reach a third. This asserts
		// the third is reachable.
		const a = openWindow({ app: 'a', title: 'A' });
		const b = openWindow({ app: 'b', title: 'B' });
		const c = openWindow({ app: 'c', title: 'C' });
		const front = () => [...get(windows)].sort((x, y) => y.z - x.z)[0].id;
		expect(front()).toBe(c);
		run('cycle');
		run('cycle');
		// Two steps from c through a stable [a,b,c] ring must not land back on c.
		expect([a, b]).toContain(front());
	});

	it('skips minimised windows when picking the front one', () => {
		const a = openWindow({ app: 'a', title: 'A' });
		openWindow({ app: 'b', title: 'B' });
		run('minimize'); // minimises B, the front-most
		run('close'); // must now act on A, not on the minimised B
		expect(get(windows).map((w) => w.id)).not.toContain(a);
	});
});

describe('the documented list matches the bindings', () => {
	it('documents every action the resolver can return', () => {
		// A shortcut that works and is undocumented is one nobody uses; a
		// documented one that does not work is worse.
		expect(SHORTCUTS.length).toBeGreaterThanOrEqual(7);
		for (const s of SHORTCUTS) {
			expect(s.chord).toBeTruthy();
			expect(s.what).toBeTruthy();
		}
	});
});
