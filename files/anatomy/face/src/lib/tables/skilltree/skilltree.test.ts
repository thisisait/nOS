/** Skill tree v2 — the framework-free modules, on the synthetic 1100-row board. */
import { describe, it, expect } from 'vitest';
import {
	wrap,
	fit,
	pickLabels,
	place,
	headline,
	lodVisible,
	boxSize,
	type Measurer
} from './labels';
import { edgePath } from './routing';
import { rimPoint, sectorAngles, sectorReach, stableAngles } from './guides';
import { ancestry, childrenMap, growIndex, parentMap, trace } from './trace';
import { diffSnapshots } from './evolution';
import { navTarget, nextMatching } from './nav';
import { radius, rectsOverlap, tweenPolar } from './geom';
import { buildSnapshot, rimSeeds, CORE_NODE } from './model';
import { CORE_ID, type TreeNode } from './types';
import { skillTreeLayout } from '../planner';
import { synthetic, systems } from './fixture';
import type { DataTableRow } from '$lib/contracts';

// A deterministic measurer: 6px per char for small, 9px for big, 11px for rim.
const mono: Measurer = {
	width: (k, t) => [...t].length * (k === 'small' ? 6 : k === 'big' ? 9 : 11)
};
const rows = synthetic() as DataTableRow[];
const tree = buildSnapshot(rows);
const visible = (n: TreeNode) => !n.dormant;
const seeds = () => [...tree.seeds, ...rimSeeds(tree, visible).seeds];

describe('labels: measured, wrapped, never clipped', () => {
	it('big and rim labels are never cut, whatever their length', () => {
		const w = wrap('The Backoffice of the Whole Estate', 'big', 50, 1, mono);
		expect(w.truncated).toBe(false);
		expect(w.lines).toEqual(['The Backoffice of the Whole Estate']);
		expect(boxSize('big', w).w).toBe(34 * 9 + 18 + 1);
	});

	it('small labels wrap at word boundaries within the budget', () => {
		const w = wrap('one two three four five six seven', 'small', 60, 5, mono);
		for (const l of w.lines) expect([...l].length * 6).toBeLessThanOrEqual(60);
		expect(w.lines.join(' ')).toBe('one two three four five six seven');
		expect(w.truncated).toBe(false);
	});

	it('past maxLines a label ends in "…" at a word boundary and still fits', () => {
		const w = wrap('alpha beta gamma delta epsilon zeta eta theta', 'small', 60, 2, mono);
		expect(w.lines.length).toBe(2);
		expect(w.truncated).toBe(true);
		expect(w.lines[1].endsWith('…')).toBe(true);
		expect(mono.width('small', w.lines[1])).toBeLessThanOrEqual(60);
	});

	it('a single long word overflows rather than being cut', () => {
		const w = wrap('docs/doctrine/digest.md', 'small', 40, 2, mono);
		expect(w.lines).toEqual(['docs/doctrine/digest.md']);
		expect(w.truncated).toBe(false);
	});

	it('fit prefers a complete headline over an ellipsis', () => {
		expect(headline('Law: the doctrine in ssot/, the constitution')).toBe('Law');
		expect(headline('BFF table GET has no tier gate — tier-managers PII')).toBe(
			'BFF table GET has no tier gate'
		);
		expect(headline('no separator here')).toBeNull();
		const seed = {
			id: 'x',
			cx: 100,
			cy: 0,
			size: 10,
			priority: 2,
			cls: 'rank-epic st-shipped',
			text: 'Law: ' + 'word '.repeat(60)
		};
		const f = fit(seed, 0.6, false, mono);
		expect(f.lines).toEqual(['Law']);
		expect(f.truncated).toBe(false);
	});

	it('pinned labels show the full title', () => {
		const seed = {
			id: 'x',
			cx: 100,
			cy: 0,
			size: 10,
			priority: 3,
			cls: 'rank-leaf',
			text: 'word '.repeat(40).trim()
		};
		const f = fit(seed, 1, true, mono);
		expect(f.truncated).toBe(false);
		expect(f.lines.join(' ')).toBe(seed.text);
	});

	it('labels hang outward: right side starts at the anchor, left side ends there', () => {
		const w = wrap('abc', 'small', 200, 1, mono);
		const r = place(
			{ id: 'r', cx: 100, cy: 0, size: 10, priority: 3, cls: 'rank-leaf', text: 'abc' },
			w,
			1
		);
		const l = place(
			{ id: 'l', cx: -100, cy: 0, size: 10, priority: 3, cls: 'rank-leaf', text: 'abc' },
			w,
			1
		);
		expect(r.align).toBe('start');
		expect(r.x).toBeGreaterThan(100);
		expect(l.align).toBe('end');
		expect(l.x + l.w).toBeLessThan(-100);
	});

	it('LOD: rim names and keystone names never show at the same zoom; the core always', () => {
		for (const z of [0.1, 0.3, 0.54, 0.55, 0.8, 1.2, 2.5]) {
			const rim = lodVisible(
				{ id: 'a', cx: 0, cy: 0, size: 0, priority: 0, cls: 'rim', text: '' },
				z
			);
			const sys = lodVisible(
				{ id: 'b', cx: 0, cy: 0, size: 30, priority: 1, cls: 'rank-system', text: '' },
				z
			);
			expect(rim, `z=${z}`).not.toBe(sys);
			expect(
				lodVisible(
					{ id: CORE_ID, cx: 0, cy: 0, size: 56, priority: 1, cls: 'rank-core', text: '' },
					z
				)
			).toBe(true);
		}
	});

	it('collision pass on the synthetic board: no two accepted labels overlap, at any zoom', () => {
		const all = seeds().filter((l) => !tree.nodes.find((n) => n.id === l.id)?.dormant);
		for (const z of [0.18, 0.6, 1, 1.6, 2.4]) {
			const out = pickLabels(all, z, { measurer: mono });
			let overlaps = 0;
			for (let i = 0; i < out.length; i++)
				for (let j = i + 1; j < out.length; j++) if (rectsOverlap(out[i], out[j])) overlaps++;
			expect(overlaps, `z=${z}`).toBe(0);
			expect(out.length).toBeGreaterThan(0);
			// the pass is a level of detail, not a blackout: the 13 rim names at fit, the 13 keystones past it
			if (z < 0.55) expect(out.filter((b) => b.kind === 'rim').length).toBe(13);
			else expect(out.filter((b) => /rank-system/.test(b.seed.cls)).length).toBe(13);
		}
	});

	it('collision pass: pinned and trail labels always survive', () => {
		const ids = tree.seeds
			.filter((l) => l.priority >= 3)
			.slice(0, 5)
			.map((l) => l.id);
		const out = pickLabels(seeds(), 0.3, {
			measurer: mono,
			pinned: new Set([ids[0]]),
			trail: new Set(ids.slice(1))
		});
		for (const id of ids)
			expect(
				out.some((b) => b.seed.id === id),
				id
			).toBe(true);
	});
});

describe('routing and guides', () => {
	it('routing: straight from the core and into the halo; Bézier otherwise', () => {
		const core = { x: 0, y: 0, rank: 'core' as const };
		const sys = { x: 340, y: 0, rank: 'system' as const };
		const epic = { x: 0, y: 704, rank: 'epic' as const };
		const halo = { x: 1900, y: 100, rank: 'halo' as const };
		expect(edgePath(core, sys)).toMatch(/^M [-\d.]+ [-\d.]+ L /);
		expect(edgePath(sys, halo)).toMatch(/ L /);
		expect(edgePath(sys, epic)).toMatch(/ C /);
		expect(edgePath(sys, epic, { route: 'orbit', elbow: 0.5 })).toMatch(/ A /);
	});

	it('rim names stand outside every visible row near their bearing, and off the milestone orbit', () => {
		const rowsOnly = tree.nodes.slice(1);
		const reach = sectorReach(rowsOnly, tree.sectors, tree.rings[1], visible);
		for (const s of tree.sectors) {
			const p = rimPoint(s, rowsOnly, reach, tree.orbit, visible, {
				wedgePad: 90,
				rimPad: 130,
				rimWindow: (14 * Math.PI) / 180,
				rimMin: tree.rings[2],
				rimOrbitClear: 110,
				rimOrbitJump: 80
			});
			const r = radius(p);
			expect(r, s.key).toBeGreaterThanOrEqual(reach.get(s.key)! + 129);
			expect(Math.abs(r - tree.orbit), s.key).toBeGreaterThanOrEqual(79);
		}
		expect(rimSeeds(tree, visible).seeds.map((s) => s.text)).toContain('The Spine');
	});

	it('sector angles: floor respected, sum is a full turn; hysteresis holds small drift', () => {
		const a = sectorAngles({ big: 199, mid: 40, one: 1, two: 1 }, 0.5, 14);
		const sum = Object.values(a).reduce((x, y) => x + y, 0);
		expect(Math.abs(sum - Math.PI * 2)).toBeLessThan(1e-9);
		for (const v of Object.values(a)) expect(v).toBeGreaterThanOrEqual((14 * Math.PI) / 180 - 1e-9);
		const b = sectorAngles({ big: 205, mid: 41, one: 1, two: 1 }, 0.5, 14);
		expect(stableAngles(a, b)).toBe(a);
		expect(stableAngles(a, sectorAngles({ big: 60, mid: 40, one: 1, two: 1 }, 0.5, 14))).not.toBe(
			a
		);
	});

	it('layout: the snapshot (2026-11-13) balance — the spine ≈ 67° for 199 rows, a bare system 14°', () => {
		const a = sectorAngles(
			{
				spine: 199,
				wits: 90,
				archive: 58,
				watch: 48,
				backoffice: 38,
				forge: 32,
				gatehouse: 27,
				vault: 22,
				keel: 12,
				commons: 11,
				stores: 1,
				clockwork: 1,
				voice: 1
			},
			0.5,
			14
		);
		const deg = (k: string) => (a[k] * 180) / Math.PI;
		expect(deg('spine')).toBeCloseTo(67, 0);
		expect(deg('stores')).toBeCloseTo(14, 5);
	});

	it('layout hysteresis: a refresh with small drift keeps the wedges; a big one re-balances', () => {
		const base = synthetic() as DataTableRow[];
		const first = skillTreeLayout(base);
		const drift = [...base, { id: 'n1', slug: 'voice-new', status: 'next', parent: 'voice' }];
		expect(skillTreeLayout(drift, undefined, first.angles).angles).toEqual(first.angles);
		const big = [
			...base,
			...Array.from({ length: 400 }, (_, i) => ({
				id: `n${i}`,
				slug: `voice-n${i}`,
				status: 'next',
				parent: 'voice'
			}))
		];
		expect(skillTreeLayout(big, undefined, first.angles).angles).not.toEqual(first.angles);
	});
});

describe('trace, grow, keyboard, evolution', () => {
	const parents = parentMap(tree.edges);
	const state = new Map(tree.nodes.map((n) => [n.id, n.state]));
	const lit = (id: string) => id === CORE_ID || ['shipped', 'allocated'].includes(state.get(id)!);

	it('trace: ancestry reaches the core; the blocker is the innermost unlit ancestor', () => {
		const blocked = tree.nodes.find((n) => n.state === 'blocked' && parents.has(n.id))!;
		const chain = ancestry(blocked.id, parents);
		expect(chain[chain.length - 1]).toBe(CORE_ID);
		const t = trace(blocked.id, parents, lit);
		expect(t.nodes.has(blocked.id)).toBe(true);
		expect(t.edges.size).toBe(chain.length);
		expect(t.blocker).not.toBeNull();
		for (const a of chain.slice(chain.indexOf(t.blocker!) + 1)) expect(lit(a), a).toBe(true);
	});

	it('grow index: a child is always one step after its parent', () => {
		const g = growIndex(
			tree.nodes.map((n) => n.id),
			tree.edges
		);
		for (const e of tree.edges) expect(g.get(e.target)).toBe(g.get(e.source)! + 1);
	});

	it('keyboard: up = parent, down = first child, left/right cycle siblings; F finds spec-ready', () => {
		const p = new Map([
			['a', 'p'],
			['b', 'p'],
			['c', 'p'],
			['p', CORE_ID]
		]);
		const children = new Map([
			['p', ['a', 'b', 'c']],
			[CORE_ID, ['p']]
		]);
		expect(navTarget('b', 'ArrowUp', { parents: p, children })).toBe('p');
		expect(navTarget('p', 'ArrowDown', { parents: p, children })).toBe('a');
		expect(navTarget('c', 'ArrowRight', { parents: p, children })).toBe('a');
		expect(navTarget('a', 'ArrowLeft', { parents: p, children })).toBe('c');
		// children walk clockwise on the real board
		const kids = childrenMap(tree.edges, (id) => tree.nodes.find((n) => n.id === id));
		const sys = kids.get(CORE_ID)!;
		expect(sys.length).toBe(13);
		expect(nextMatching(['x', 'y', 'z'], 'y', (id) => id === 'x')).toBe('x');
	});

	it('evolution diff: sprouted, withered, ignited, shifted, moved; the tween slides along the ring', () => {
		const base: TreeNode = {
			...CORE_NODE,
			id: 'a',
			x: 100,
			y: 0,
			size: 10,
			rank: 'leaf',
			state: 'frontier',
			spec: 'spec-ready'
		};
		const prev = {
			nodes: [{ ...base }, { ...base, id: 'b' }, { ...base, id: 'c', state: 'doing' as const }]
		};
		const next = {
			nodes: [
				{ ...base, state: 'shipped' as const },
				{ ...base, id: 'c', state: 'review' as const, x: 140 },
				{ ...base, id: 'd' }
			]
		};
		const d = diffSnapshots(prev, next);
		expect(d.ignited).toEqual(['a']);
		expect(d.sprouted).toEqual(['d']);
		expect(d.withered.map((n) => n.id)).toEqual(['b']);
		expect(d.shifted).toEqual([{ id: 'c', from: 'doing', to: 'review' }]);
		expect(d.moved.length).toBe(1);
		const m = tweenPolar({ x: 500, y: 0 }, { x: 0, y: 500 }, 0.5);
		expect(Math.abs(radius(m) - 500)).toBeLessThan(1e-9);
	});

	it('snapshot: the core leads, systems hang off it, states and specs match the frontier rule', () => {
		expect(tree.nodes[0].id).toBe(CORE_ID);
		const sysEdges = tree.edges.filter((e) => e.source === CORE_ID);
		expect(sysEdges.length).toBe(13);
		expect(sysEdges.every((e) => e.cls === 'grown')).toBe(true);
		const ready = tree.nodes.find((n) => n.spec === 'spec-ready');
		expect(ready?.state).toMatch(/frontier|allocated/);
		expect(buildSnapshot(systems() as DataTableRow[]).edges.length).toBe(13);
	});
});
