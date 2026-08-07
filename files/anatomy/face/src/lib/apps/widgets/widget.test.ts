/**
 * Widget render smoke — the seven nodes actually reach the screen.
 *
 * Server-side render only (no DOM, no fetch): `onMount` and `$effect` do not
 * run, so what this proves is the BUILD-TIME half — the artifact is read, the
 * spotlight rule selects seven real nodes, they are drawn, the rule is
 * printed, and the tier gate holds. The live half (the 60 s Pulse poll and
 * its four states) is proven by the shape gates in
 * `tests/anatomy/test_face_app_form_axis.py`.
 *
 * It is here rather than in pytest because only the Svelte compiler can tell
 * you whether a component renders; a regex over the source cannot.
 */
import { describe, expect, it } from 'vitest';
import { render } from 'svelte/server';
import AnatomyWidget from './AnatomyWidget.svelte';
import WidgetLayer from './WidgetLayer.svelte';
import { projectGraph, spotlight } from '$lib/anatomy/graph';
import raw from '$lib/anatomy/anatomy-graph.json';
import { ANON, type Identity } from '$lib/contracts';
import { registerBuiltinNativeApps, _resetRegistry } from '$lib/apps/native';

const ADMIN: Identity = {
	uid: 'u1',
	username: 'op',
	email: 'op@example.invalid',
	groups: ['nos-admins'],
	authenticated: true
};

const spot = spotlight(projectGraph(raw), 7);

/** Svelte's SSR hydration anchors (`<!--[-->`) are not content. */
const visible = (html: string) => html.replace(/<!--.*?-->/g, '').trim();

describe('AnatomyWidget (SSR)', () => {
	it('draws the seven nodes the rule chose, by their real ids', () => {
		const { body } = render(AnatomyWidget, { props: { identity: ADMIN } });
		expect(spot.nodes).toHaveLength(7);
		for (const n of spot.nodes) {
			// The full id is in the node's tooltip/description; the visible
			// label is clipped, so assert on what the operator can verify.
			expect(body).toContain(n.description.slice(0, 40));
		}
	});

	it('prints the selection rule and the component count', () => {
		const { body } = render(AnatomyWidget, { props: { identity: ADMIN } });
		expect(body).toContain('mutex pairs excluded');
		expect(body).toContain(`${spot.components} component`);
	});

	it('says the graph is build-time and the state is polled — never "live"', () => {
		const { body } = render(AnatomyWidget, { props: { identity: ADMIN } });
		expect(body).toContain('build-time artifact');
		expect(body).toContain('polled every 60');
		expect(body.toLowerCase()).not.toContain('[live]');
	});

	it('opens with "asking", not with a clean bill of health', () => {
		const { body } = render(AnatomyWidget, { props: { identity: ADMIN } });
		expect(body).toContain('asking Pulse');
		expect(body).not.toContain('data-kind="empty"');
	});

	it('renders NOTHING for a non-admin — not an error, not a placeholder', () => {
		for (const id of [ANON, { ...ADMIN, groups: ['nos-users'] }]) {
			const { body } = render(AnatomyWidget, { props: { identity: id } });
			expect(visible(body)).toBe('');
		}
		expect(visible(render(AnatomyWidget, { props: {} }).body)).toBe('');
	});

	it('names itself in the graph it draws — the recursion, checkable', () => {
		const { body } = render(AnatomyWidget, { props: { identity: ADMIN } });
		expect(body).toContain('faceapp:anatomy-widget');
	});
});

describe('WidgetLayer (SSR)', () => {
	it('renders every registered widget and nothing when there are none', () => {
		_resetRegistry();
		expect(visible(render(WidgetLayer, { props: { identity: ADMIN } }).body)).toBe('');
		registerBuiltinNativeApps();
		const { body } = render(WidgetLayer, { props: { identity: ADMIN } });
		expect(body).toContain('widget-layer');
	});
});
