/** Browser Measurer: canvas measureText, calibrated once per kind against a real DOM span, so
 *  the numbers follow whatever font the browser actually resolved (AIT Mono, SF Mono, Menlo…).
 *  The probes are spans the VIEW renders with the real (Svelte-scoped) label classes — a span
 *  made here with className "lbl rim" would miss the component's scope hash and measure the
 *  body font instead (found on the live board 11-13: rim boxes 20 % too narrow).
 *  reset() after document.fonts.ready and on every 'loadingdone'. */
import type { LabelKind, Measurer } from './labels';

const SAMPLE = 'The Backoffice — quick organ systems 0123';

interface KindFont {
	font: string;
	upper: boolean;
	tracking: number;
	ratio: number;
}

export function createBrowserMeasurer(
	probeOf: (kind: LabelKind) => HTMLElement
): Measurer & { reset(): void } {
	const ctx = document.createElement('canvas').getContext('2d');
	const cache = new Map<string, number>();
	let fonts: Partial<Record<LabelKind, KindFont>> = {};

	const raw = (f: KindFont, text: string) => {
		const t = f.upper ? text.toUpperCase() : text;
		if (!ctx) return t.length * 7; // no canvas (a test DOM): a safe over-estimate
		ctx.font = f.font;
		return ctx.measureText(t).width + f.tracking * [...t].length;
	};

	function probe(kind: LabelKind): KindFont {
		const s = probeOf(kind);
		const was = s.textContent;
		s.textContent = SAMPLE;
		const cs = getComputedStyle(s);
		const px = (v: string) => parseFloat(v) || 0;
		const dom =
			s.getBoundingClientRect().width -
			px(cs.paddingLeft) -
			px(cs.paddingRight) -
			px(cs.borderLeftWidth) -
			px(cs.borderRightWidth);
		const f: KindFont = {
			font: `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`,
			upper: cs.textTransform === 'uppercase',
			tracking: px(cs.letterSpacing),
			ratio: 1
		};
		s.textContent = was;
		const c = raw(f, SAMPLE);
		f.ratio = c > 0 && dom > 0 ? dom / c : 1;
		return f;
	}

	return {
		width(kind, text) {
			const key = kind + '\u0000' + text;
			const hit = cache.get(key);
			if (hit !== undefined) return hit;
			const f = (fonts[kind] ??= probe(kind));
			const w = raw(f, text) * f.ratio;
			cache.set(key, w);
			return w;
		},
		reset() {
			fonts = {};
			cache.clear();
		}
	};
}
