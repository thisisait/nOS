// What an action would do to a tree node, list item or record field (renderers.rs Delta).
import type { TreeNode } from './wire';

export type Delta = 'added' | 'removed' | 'changed';
export type View = 'before' | 'changes' | 'after';

export const MARK: Record<Delta, string> = { added: '+', removed: '−', changed: '~' };
export const VIEWS: [View, string][] = [
	['before', 'Před'],
	['changes', 'Změny'],
	['after', 'Po']
];

/** An added or removed parent passes its state down; a changed one passes nothing (Delta::inherit). */
export const inherit = (own: Delta | undefined, parent: Delta | undefined) =>
	parent === 'added' || parent === 'removed' ? parent : own;

/** Před hides what is added, Po what is removed, Změny shows all. */
export const shownIn = (d: Delta | undefined, v: View) =>
	!(v === 'before' && d === 'added') && !(v === 'after' && d === 'removed');

/** Every node's resolved delta, depth first. */
export const treeDeltas = (nodes: TreeNode[], parent?: Delta): (Delta | undefined)[] =>
	nodes.flatMap((n) => {
		const d = inherit(n.delta, parent);
		return [d, ...treeDeltas(n.children ?? [], d)];
	});

export const tally = (ds: (Delta | undefined)[]) => {
	const n = (d: Delta) => ds.filter((x) => x === d).length;
	return `+${n('added')} −${n('removed')} ~${n('changed')}`;
};
