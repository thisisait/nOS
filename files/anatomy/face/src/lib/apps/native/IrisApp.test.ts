// @vitest-environment happy-dom
// Iris as a face app: it mounts the shared Iris on the transport it is given, draws a
// thalamus line, and closes that transport with the window.
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import fixture from '../../../../../contracts/thalamus-shell.fixture.json';
import { fakeTransport } from '$lib/iris/transport.fake';
import type { ToShell } from '$lib/iris/wire';
import IrisApp from './IrisApp.svelte';
import { _resetRegistry, faceApps, registerBuiltinNativeApps } from './registry';

const fx = fixture as unknown as { to_shell: { case: string; msg: ToShell }[] };
const settle = async () => {
	for (let i = 0; i < 20; i++) await Promise.resolve();
	flushSync();
};

afterEach(() => {
	document.body.replaceChildren();
	_resetRegistry();
});

describe('IrisApp', () => {
	it('mounts Iris on its transport and renders a to_shell render line', async () => {
		const fake = fakeTransport();
		let closed = 0;
		const app = mount(IrisApp, {
			target: document.body,
			props: { transport: { ...fake.transport, close: () => closed++ } }
		});
		await settle();
		expect(fake.connects).toBe(1);
		fake.shell(fx.to_shell.find((c) => c.case === 'a markdown reply')!.msg);
		await settle();
		expect(document.body.textContent).toContain('Next on the roadmap');
		unmount(app);
		expect(closed).toBe(1);
	});

	it('is registered as a view with its own state namespace', () => {
		registerBuiltinNativeApps();
		const iris = faceApps().find((a) => a.slug === 'iris');
		expect(iris).toMatchObject({
			title: 'Iris',
			form: 'view',
			stateNamespace: 'app.iris',
			apiScopes: ['iris']
		});
	});
});
