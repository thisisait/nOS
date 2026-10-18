// The markdown a model writes, as a tree of text nodes for Markdown.svelte: never HTML.
// Headings 1-3, paragraphs, lists of two levels, code fences; inline strong, em, code, link.
// An image is words, [obrázek: alt]. Its url is not drawn and nothing is fetched.
// Anything else is literal text, so a string that is not markdown is one paragraph of itself.

export type Inline =
	| { t: 'text' | 'strong' | 'em' | 'code'; text: string }
	/** Drawn as `label (url)`: a click would navigate the webview. url is null unless http(s). */
	| { t: 'link'; text: string; url: string | null };

export type Block =
	| { t: 'h'; level: 1 | 2 | 3; inl: Inline[] }
	| { t: 'p'; inl: Inline[] }
	| { t: 'ul'; items: { inl: Inline[]; sub: Inline[][] }[] }
	/** `n` is the number written on that line, so the marker is not 1, 2, 3. */
	| { t: 'ol'; items: { n: number; inl: Inline[] }[] }
	| { t: 'code'; text: string }
	| { t: 'hr' };

// A label holds no "[": else every unclosed "[" re-reads the rest (quadratic).
const INLINE =
	/`([^`\n]+)`|\*\*(.+?)\*\*|\*([^*\s](?:[^*]*[^*\s])?)\*|!\[([^[\]\n]*)\]\(([^)\s]+)\)|\[([^[\]\n]+)\]\(([^)\s]+)\)/g;

export function inline(s: string): Inline[] {
	const out: Inline[] = [];
	let at = 0;
	for (const m of s.matchAll(INLINE)) {
		if (m.index > at) out.push({ t: 'text', text: s.slice(at, m.index) });
		const [, code, strong, em, image, , label, url] = m;
		if (code !== undefined) out.push({ t: 'code', text: code });
		else if (strong !== undefined) out.push({ t: 'strong', text: strong });
		else if (em !== undefined) out.push({ t: 'em', text: em });
		else if (image !== undefined) out.push({ t: 'text', text: `[obrázek: ${image}]` });
		else out.push({ t: 'link', text: label, url: /^https?:\/\//i.test(url) ? url : null });
		at = m.index + m[0].length;
	}
	if (at < s.length) out.push({ t: 'text', text: s.slice(at) });
	return out;
}

const HEADING = /^(#{1,3})\s+(.*)$/;
const UL = /^(\s*)[-*+]\s+(.*)$/;
const OL = /^\s*(\d+)[.)]\s+(.*)$/;

export function parse(text: string): Block[] {
	const lines = text.split(/\r?\n/);
	const out: Block[] = [];
	let para: string[] = [];
	const flush = () => {
		if (para.length) out.push({ t: 'p', inl: inline(para.join('\n')) });
		para = [];
	};
	for (let i = 0; i < lines.length; i++) {
		const l = lines[i];
		if (l.trimStart().startsWith('```')) {
			flush();
			const body: string[] = [];
			while (++i < lines.length && !lines[i].trimStart().startsWith('```')) body.push(lines[i]);
			out.push({ t: 'code', text: body.join('\n') });
			continue;
		}
		if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(l)) {
			flush();
			out.push({ t: 'hr' });
			continue;
		}
		const h = HEADING.exec(l);
		const ul = UL.exec(l);
		const ol = ul ? null : OL.exec(l);
		if (h) {
			flush();
			out.push({ t: 'h', level: h[1].length as 1 | 2 | 3, inl: inline(h[2]) });
		} else if (ul || ol) {
			flush();
			const last = out[out.length - 1];
			if (ul) {
				const item = inline(ul[2]);
				// Two spaces under an item is the second level; a deeper indent stays there.
				if (ul[1].length >= 2 && last?.t === 'ul' && last.items.length)
					last.items[last.items.length - 1].sub.push(item);
				else if (last?.t === 'ul') last.items.push({ inl: item, sub: [] });
				else out.push({ t: 'ul', items: [{ inl: item, sub: [] }] });
			} else {
				const item = { n: Number(ol![1]), inl: inline(ol![2]) };
				if (last?.t === 'ol') last.items.push(item);
				else out.push({ t: 'ol', items: [item] });
			}
		} else if (l.trim() === '') flush();
		else para.push(l);
	}
	flush();
	return out;
}
