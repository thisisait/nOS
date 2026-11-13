/** Keyboard: one tab stop for the whole tree (roving tabindex), arrows walk the tree.
 *    ↑ parent · ↓ first child · ← / → previous / next sibling (clockwise order)
 *    F next spec-ready frontier · Enter select · Esc clear */
import { CORE_ID } from './types';

export interface NavMaps {
	parents: Map<string, string>;
	children: Map<string, string[]>;
}

export function navTarget(current: string, key: string, m: NavMaps): string | null {
	if (key === 'ArrowUp') return m.parents.get(current) ?? null;
	if (key === 'ArrowDown') return m.children.get(current)?.[0] ?? null;
	if (key === 'ArrowLeft' || key === 'ArrowRight') {
		const parent = m.parents.get(current) ?? (current === CORE_ID ? null : CORE_ID);
		const sibs = parent ? (m.children.get(parent) ?? []) : [];
		const i = sibs.indexOf(current);
		if (i < 0 || sibs.length < 2) return null;
		const step = key === 'ArrowRight' ? 1 : -1;
		return sibs[(i + step + sibs.length) % sibs.length];
	}
	return null;
}

/** Next id in `order` after `current` that satisfies `pred`, wrapping. */
export function nextMatching(
	order: readonly string[],
	current: string | null,
	pred: (id: string) => boolean
): string | null {
	const start = current ? order.indexOf(current) : -1;
	for (let k = 1; k <= order.length; k++) {
		const id = order[(start + k + order.length) % order.length];
		if (pred(id)) return id;
	}
	return null;
}
