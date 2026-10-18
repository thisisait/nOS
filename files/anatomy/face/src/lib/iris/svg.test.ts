// A <title> outside an <svg> compiles in the HTML namespace on the client
// (from_html), so a mark gets no tooltip and no name. svelte/server strings hide
// it; only the client compile shows it. A <title> after <svg in one template is SVG.
import { readdirSync, readFileSync } from 'node:fs';
import { compile } from 'svelte/compiler';
import { describe, expect, it } from 'vitest';

const dir = new URL('./', import.meta.url);
const files = readdirSync(dir).filter((f) => f.endsWith('.svelte'));

describe('every <title> is an SVG title on the client', () => {
	it.each(files)('%s builds no <title> through an HTML template', (f) => {
		const js = compile(readFileSync(new URL(f, dir), 'utf8'), { filename: f, generate: 'client' })
			.js.code;
		expect(js.match(/from_html\(`(?:(?!<svg)[^`])*<title/g) ?? []).toEqual([]);
	});
});
