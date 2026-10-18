// @vitest-environment happy-dom
// Iris on a fake transport: what the face and the pupil both mount. The wire is the contract
// fixture's, so a line the thalamus can send is a line this window draws.
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
// Imported, not read: under happy-dom import.meta.url is not a file URL.
import fixture from '../../../../contracts/thalamus-shell.fixture.json';
import Iris from './Iris.svelte';
import { fakeTransport } from './transport.fake';
import type { Act, Acted, Limb } from '$lib/limbs/types';
import type { ToShell } from './wire';

const fx = fixture as unknown as { to_shell: { case: string; msg: ToShell }[] };
const sample = (name: string) => fx.to_shell.find((c) => c.case === name)!.msg;

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
	if (app) unmount(app);
	app = null;
	document.body.replaceChildren();
});

// Every promise Iris awaits on the fake is already settled: a few turns of the queue drain them.
const settle = async () => {
	for (let i = 0; i < 20; i++) await Promise.resolve();
	flushSync();
};

async function open(props: { limbs?: () => Limb[]; act?: (a: Act) => Promise<Acted> } = {}) {
	const fake = fakeTransport();
	app = mount(Iris, { target: document.body, props: { transport: fake.transport, ...props } });
	await settle();
	return fake;
}

const LIMBS: Limb[] = [
	{
		app: 'desktop',
		action: 'open_app',
		params: { slug: { type: 'string', required: true } },
		writes: false,
		says: 'Open a face app'
	}
];

describe('Iris in the face: limbs and marks (contract 8)', () => {
	it('asks for the catalogue, and declares limbs only when the face hands it some', async () => {
		const bare = await open();
		expect(bare.sent.map((m) => m.t)).toContain('catalogue');
		expect(bare.sent.some((m) => m.t === 'limbs')).toBe(false);
		unmount(app!);
		app = null;
		const face = await open({ limbs: () => LIMBS });
		expect(face.sent).toContainEqual({ t: 'limbs', limbs: LIMBS });
		expect(face.sent.slice(0, 2).map((m) => m.t)).toEqual(['resume', 'workspace_load']);
	});

	it('answers an act through the face, and without limbs answers no', async () => {
		const seen: Act[] = [];
		const face = await open({
			limbs: () => LIMBS,
			act: async (a) => (seen.push(a), { act: a.act, ok: true, result: 'opened' })
		});
		const a = sample('Iris acts in the face') as Extract<ToShell, { t: 'act' }>;
		face.shell(a);
		await settle();
		expect(seen.map((x) => [x.app, x.action, x.params])).toEqual([
			['desktop', 'open_app', { slug: 'tables' }]
		]);
		expect(face.sent).toContainEqual({ t: 'acted', act: a.act, ok: true, result: 'opened' });
		unmount(app!);
		app = null;
		const pupil = await open();
		pupil.shell(a);
		await settle();
		const said = pupil.sent.find((m) => m.t === 'acted');
		expect(said).toMatchObject({ t: 'acted', act: a.act, ok: false });
	});

	it('marks the composer from the catalogue, behind a textarea that keeps the text', async () => {
		const fake = await open();
		fake.shell(sample("the person's catalogue"));
		await settle();
		const box = document.querySelector('textarea')!;
		box.value = 'faktury pro Acme dnes';
		box.dispatchEvent(new Event('input', { bubbles: true }));
		flushSync();
		const layer = document.querySelector('.marks')!;
		expect(layer.getAttribute('aria-hidden')).toBe('true');
		expect(layer.textContent).toContain('faktury pro Acme dnes');
		const marked = [...layer.querySelectorAll('mark')].map((m) => [m.textContent, m.dataset.kind]);
		expect(marked).toEqual([
			['faktury', 'table'],
			['Acme', 'option'],
			['dnes', 'period']
		]);
		// The textarea stays the control a screen reader and the keyboard reach; only the layer is hidden.
		expect(box.closest('[aria-hidden]')).toBeNull();
		expect(box.value).toBe('faktury pro Acme dnes');
	});
});

describe('Iris on a transport', () => {
	it('connects once, then resumes the session and asks for the layout before anything else', async () => {
		const fake = await open();
		expect(fake.connects).toBe(1);
		expect(fake.sent.slice(0, 2).map((m) => m.t)).toEqual(['resume', 'workspace_load']);
	});

	it('draws a to_shell line from the fixture', async () => {
		const fake = await open();
		fake.shell(sample('a markdown reply'));
		await settle();
		expect(document.body.textContent).toContain('Next on the roadmap');
	});

	it('sends a decision exactly once, however often it is clicked', async () => {
		const fake = await open();
		const ask = sample('a row edit awaits approval') as Extract<ToShell, { t: 'approval_request' }>;
		fake.shell(ask);
		await settle();
		const reject = [...document.querySelectorAll('button')].find(
			(b) => b.textContent?.trim() === 'reject'
		)!;
		expect(reject).toBeTruthy();
		// A browser renders between two clicks: the second lands on the card the first one closed.
		reject.click();
		flushSync();
		reject.click();
		await settle();
		expect(document.querySelector(`[data-approval="${ask.approval}"]`)).toBeNull();
		const decided = fake.sent.filter((m) => m.t === 'approval_decision');
		expect(decided).toEqual([
			{ t: 'approval_decision', approval: ask.approval, decision: 'reject', note: null }
		]);
	});

	// Contract 9 (operator 2026-10-18): each tab its own conversation, /branch and /clear, and a Stop.
	it('resumes the tab it shows, branches and clears by slash command, and stops a running turn', async () => {
		const fake = await open();
		expect(fake.sent[0]).toEqual({ t: 'resume', workspace: 'ws1' });
		const s = sample('session opened') as Extract<ToShell, { t: 'session' }>;
		fake.shell(s);
		await settle();
		const type = async (text: string) => {
			const box = document.querySelector('textarea')!;
			box.value = text;
			box.dispatchEvent(new Event('input', { bubbles: true }));
			flushSync();
			box.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
			await settle();
		};
		await type('/branch');
		const tabs = () => [...document.querySelectorAll('[role="tab"]')];
		expect(tabs()).toHaveLength(2);
		const branch = fake.sent.find((m) => m.t === 'branch') as { t: 'branch'; workspace: string };
		expect(branch.workspace).toMatch(/^ws/);
		expect(branch.workspace).not.toBe('ws1');
		await type('/clear');
		expect(fake.sent.at(-1)).toEqual({ t: 'clear' });
		expect(fake.sent.some((m) => m.t === 'turn')).toBe(false);
		// Showing the first tab again resumes its session.
		(tabs()[0] as HTMLElement).click();
		await settle();
		expect(fake.sent.at(-1)).toEqual({ t: 'resume', workspace: 'ws1' });
		const stop = () =>
			[...document.querySelectorAll('button')].find((b) => b.textContent?.trim() === 'stop');
		expect(stop()).toBeUndefined();
		fake.shell({ t: 'activity', session: s.session, phase: 'thinking' });
		await settle();
		stop()!.click();
		await settle();
		expect(fake.sent.at(-1)).toEqual({ t: 'stop', session: s.session });
		fake.shell({ t: 'activity', session: s.session, phase: 'idle' });
		await settle();
		expect(stop()).toBeUndefined();
	});
});
