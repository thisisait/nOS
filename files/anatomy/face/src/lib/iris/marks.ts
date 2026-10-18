/**
 * Marks the person's input against their catalogue (row iris-input-highlighting).
 * Columns mirror KEAP's /data/schema/columns, which thalamus catalogue() reads (serve.rs).
 * Pure: no DOM, no deps. Offsets are UTF-16 indices into the original text.
 */
export type Catalogue = {
	tables: { id: string; title: string; columns: { key: string; label?: string; kind: string; options?: string[] }[] }[];
};
export type Span = {
	start: number;
	end: number;
	kind: 'table' | 'column' | 'option' | 'date' | 'period' | 'number' | 'operator';
	ref?: string;
};

// Steps 1-2 of slugifyUid's fold (lib/security/uid.ts); per char, so offsets map back.
function fold(text: string): { f: string; at: number[] } {
	let f = '';
	const at: number[] = [];
	let i = 0;
	for (const ch of text) {
		const g = ch.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase();
		for (let k = 0; k < g.length; k++) at.push(i);
		f += g;
		i += ch.length;
	}
	at.push(i);
	return { f, at };
}

// Words in their folded form; refs are the names serve.rs resolves (today … this_year).
const PERIODS: [string, string[]][] = [
	['today', ['today', 'dnes', 'dneska']],
	['yesterday', ['yesterday', 'vcera']],
	['this_week', ['this week', 'this_week', 'tento tyden', 'tomto tydnu', 'tenhle tyden']],
	['this_month', ['this month', 'this_month', 'tento mesic', 'tomto mesici', 'tenhle mesic']],
	['last_month', ['last month', 'last_month', 'minuly mesic', 'minulem mesici', 'minulej mesic']],
	['this_year', ['this year', 'this_year', 'tento rok', 'tomto roce', 'letos']]
];
const OPERATORS: [string, string[]][] = [
	['between', ['between', 'mezi']],
	['gt', ['more than', 'greater than', 'vice nez', 'vic nez']],
	['lt', ['less than', 'fewer than', 'mene nez', 'min nez']],
	['sum', ['sum', 'total of', 'soucet']],
	['avg', ['average', 'avg', 'mean', 'prumer']],
	['count', ['count', 'pocet']]
];

const W = '[\\p{L}\\p{N}]';
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '\\s+');
/** A whole-word pattern: no match inside a longer word. */
const word = (src: string) => new RegExp(`(?<!${W})(?:${src})(?!${W})`, 'gu');

type Rule = { re: RegExp; kind: Span['kind']; ref?: string };
const FIXED: Rule[] = [
	{ re: word('\\d{4}-\\d{2}-\\d{2}'), kind: 'date' },
	{ re: word('\\d{1,2}\\.\\s?\\d{1,2}\\.(?:\\s?\\d{4})?'), kind: 'date' },
	{ re: new RegExp(`(?<![\\p{L}\\p{N}.,])\\d+(?:[.,]\\d+)?(?!${W})`, 'gu'), kind: 'number' },
	{ re: word('top\\s+\\d+'), kind: 'operator', ref: 'top' },
	...PERIODS.map(([ref, ws]) => ({ re: word(ws.map(esc).join('|')), kind: 'period' as const, ref })),
	...OPERATORS.map(([ref, ws]) => ({ re: word(ws.map(esc).join('|')), kind: 'operator' as const, ref }))
];

function catalogueRules(cat: Catalogue): Rule[] {
	const rules: Rule[] = [];
	// ponytail: exact folded names, no Czech stemming ("fakturách" misses "Faktury"); add when the bench says so.
	const add = (name: string | undefined, kind: Span['kind'], ref: string) => {
		const n = name ? fold(name.trim()).f : '';
		if (n.length >= 2) rules.push({ re: word(esc(n)), kind, ref });
	};
	for (const t of cat.tables) {
		add(t.title, 'table', t.id);
		add(t.id, 'table', t.id);
		for (const c of t.columns) {
			add(c.label, 'column', `${t.id}.${c.key}`);
			add(c.key, 'column', `${t.id}.${c.key}`);
			for (const o of c.options ?? []) add(o, 'option', `${t.id}.${c.key}=${o}`);
		}
	}
	return rules;
}

export function mark(text: string, cat: Catalogue): Span[] {
	const { f, at } = fold(text);
	const found: Span[] = [];
	for (const r of [...catalogueRules(cat), ...FIXED]) {
		for (const m of f.matchAll(r.re)) found.push({ start: m.index, end: m.index + m[0].length, kind: r.kind, ref: r.ref });
	}
	// Longest first, then earliest; the stable sort keeps catalogue order on a tie.
	found.sort((a, b) => b.end - b.start - (a.end - a.start) || a.start - b.start);
	const taken: Span[] = [];
	for (const s of found) if (!taken.some((t) => s.start < t.end && t.start < s.end)) taken.push(s);
	return taken
		.sort((a, b) => a.start - b.start)
		.map((s) => ({ start: at[s.start], end: at[s.end], kind: s.kind, ...(s.ref ? { ref: s.ref } : {}) }));
}
