/** The skill tree's render model (skill-tree v2): what the layout hands the view. PURE types,
 *  shared by the framework-free modules in this folder and the Svelte view. */
import type { GemRank, TreeState } from '../planner';

export type Spec = '' | 'spec-ready' | 'spec-needed';
export type EdgeClass = '' | 'grown' | 'front';

export interface Point {
	x: number;
	y: number;
}

export interface TreeNode extends Point {
	id: string;
	/** Box size in flow px: core 56, system 30, epic 14, leaf 10, halo 8 (GEM_SIZE). */
	size: number;
	rank: GemRank;
	state: TreeState;
	spec: Spec;
	title: string;
	system: string;
	depth: number;
	dormant: boolean;
}

export interface TreeEdge {
	source: string;
	target: string;
	cls: EdgeClass;
}

export interface Sector {
	key: string;
	/** Radians, screen convention (y down, clockwise positive). */
	from: number;
	to: number;
}

export interface LabelSeed {
	id: string;
	/** Anchor in flow px (the gem centre, or the rim point). */
	cx: number;
	cy: number;
	/** Gem box size in flow px; 0 for a rim name. */
	size: number;
	text: string;
	/** An optional headline (≤ ~28 chars); until the roadmap carries one, headline() derives it. */
	short?: string;
	/** 0 rim · 1 core/system · 2 epic · 3+ rows (lower wins the collision pass). */
	priority: number;
	/** Classes copied onto span.lbl, e.g. "rank-leaf st-review" or "rim". */
	cls: string;
}

export const CORE_ID = '__core__';
