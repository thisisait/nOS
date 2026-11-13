/** Test boards for the planner and the skill tree (imported by *.test.ts only). */
import { ORGAN_RING } from '../planner';

export const RING = [
	'gatehouse',
	'spine',
	'stores',
	'vault',
	'keel',
	'archive',
	'forge',
	'backoffice',
	'commons',
	'watch',
	'wits',
	'clockwork',
	'voice'
];

export const systems = () => RING.map((s) => ({ id: s, slug: s, status: 'shipped', parent: '' }));

/** A fully hung board the size of the real one: 13 systems, 3..20 epics each, 0..12 leaves,
 *  some grand-leaves, one 52-fan epic, 6 milestones; deterministic (LCG). Live-shaped titles:
 *  a system's row reads "The Spine: its tells", a row's is a sentence. */
export function synthetic(): Record<string, unknown>[] {
	let seed = 7;
	const rnd = (n: number) => (seed = (seed * 48271) % 2147483647) % n;
	const rows: Record<string, unknown>[] = systems();
	const statuses = ['shipped', 'active', 'next', 'queued', 'review', 'doing', 'parked'];
	for (const sys of RING) {
		const epics = 3 + rnd(18);
		for (let e = 0; e < epics; e++) {
			const es = `${sys}-e${e}`;
			rows.push({ slug: es, status: statuses[rnd(4)], parent: sys });
			const leaves = sys === 'spine' && e === 0 ? 52 : rnd(13);
			for (let l = 0; l < leaves; l++) {
				const ls = `${es}-l${l}`;
				rows.push({ slug: ls, status: statuses[rnd(7)], parent: es });
				if (rnd(5) === 0)
					for (let g = 0; g < 1 + rnd(4); g++)
						rows.push({ slug: `${ls}-g${g}`, status: statuses[rnd(7)], parent: ls });
			}
		}
	}
	for (let m = 0; m < 6; m++) rows.push({ slug: `rel-02${m}`, status: 'next', parent: '' });
	while (rows.length < 1100)
		rows.push({ slug: `extra-${rows.length}`, status: 'next', parent: 'voice-e1' });
	const tells = new Map(ORGAN_RING.map((r) => [r.key, `${r.title}: ${r.tells}`]));
	const words = 'the reader that knows what needs a human has no surface for the estate'.split(' ');
	const spec = 'Goal: x.\nSlice 1: x.\nE2E: x.\nMust not: x.';
	return rows.map((r, i) => ({
		...r,
		id: `s${i}`,
		body: r.status === 'next' && i % 7 === 0 ? spec : '', // every 7th open row carries a ready spec
		title:
			tells.get(r.slug as string) ??
			`${r.slug} — ${Array.from({ length: 5 + rnd(9) }, () => words[rnd(words.length)]).join(' ')}`
	}));
}
