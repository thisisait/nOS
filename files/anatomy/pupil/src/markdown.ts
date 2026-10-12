// The markdown a model writes, as a tree of text nodes for Markdown.svelte: never HTML.
// Headings 1-3, paragraphs, one-level lists, code fences; inline strong, em, code, link.
// Anything else is literal text, so a string that is not markdown is one paragraph of itself.

export type Inline =
	| { t: 'text' | 'strong' | 'em' | 'code'; text: string }
	/** Drawn as `label (url)`: a click would navigate the webview. url is null unless http(s). */
	| { t: 'link'; text: string; url: string | null };

export type Block =
	| { t: 'h'; level: 1 | 2 | 3; inl: Inline[] }
	| { t: 'p'; inl: Inline[] }
	| { t: 'ul' | 'ol'; items: Inline[][] }
	| { t: 'code'; text: string };

const INLINE = /`([^`\n]+)`|\*\*(.+?)\*\*|\*([^*\s](?:[^*]*[^*\s])?)\*|\[([^\]\n]+)\]\(([^)\s]+)\)/g;

export function inline(s: string): Inline[] {
	const out: Inline[] = [];
	let at = 0;
	for (const m of s.matchAll(INLINE)) {
		if (m.index > at) out.push({ t: 'text', text: s.slice(at, m.index) });
		const [, code, strong, em, label, url] = m;
		if (code !== undefined) out.push({ t: 'code', text: code });
		else if (strong !== undefined) out.push({ t: 'strong', text: strong });
		else if (em !== undefined) out.push({ t: 'em', text: em });
		else out.push({ t: 'link', text: label, url: /^https?:\/\//i.test(url) ? url : null });
		at = m.index + m[0].length;
	}
	if (at < s.length) out.push({ t: 'text', text: s.slice(at) });
	return out;
}

const HEADING = /^(#{1,3})\s+(.*)$/;
const ITEM = { ul: /^\s*[-*+]\s+(.*)$/, ol: /^\s*\d+[.)]\s+(.*)$/ };

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
		const h = HEADING.exec(l);
		const kind = ITEM.ul.test(l) ? 'ul' : ITEM.ol.test(l) ? 'ol' : null;
		if (h) {
			flush();
			out.push({ t: 'h', level: h[1].length as 1 | 2 | 3, inl: inline(h[2]) });
		} else if (kind) {
			flush();
			const item = inline(ITEM[kind].exec(l)![1]);
			const last = out[out.length - 1];
			if (last?.t === kind) last.items.push(item);
			else out.push({ t: kind, items: [item] });
		} else if (l.trim() === '') flush();
		else para.push(l);
	}
	flush();
	return out;
}
