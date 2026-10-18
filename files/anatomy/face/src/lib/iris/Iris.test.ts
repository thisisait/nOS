// @vitest-environment happy-dom
// Iris on a fake transport: what the face and the pupil both mount. The wire is the contract
// fixture's, so a line the thalamus can send is a line this window draws.
import { readFileSync } from 'node:fs';
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import Iris from './Iris.svelte';
import { fakeTransport } from './transport.fake';
import type { ToShell } from './wire';

const FIXTURE = new URL('../../../../contracts/thalamus-shell.fixture.json', import.meta.url);
const fx = JSON.parse(readFileSync(FIXTURE, 'utf8')) as {
	to_shell: { case: string; msg: ToShell }[];
};
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

async function open() {
	const fake = fakeTransport();
	app = mount(Iris, { target: document.body, props: { transport: fake.transport } });
	await settle();
	return fake;
}

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
		reject.click();
		reject.click();
		await settle();
		const decided = fake.sent.filter((m) => m.t === 'approval_decision');
		expect(decided).toEqual([
			{ t: 'approval_decision', approval: ask.approval, decision: 'reject', note: null }
		]);
	});
});
