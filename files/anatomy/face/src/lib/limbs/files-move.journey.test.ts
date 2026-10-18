// @vitest-environment happy-dom
// The first write limb end to end, through Iris on the fake transport: the thalamus asks with
// an action_approval card for files.move, the person approves, the thalamus sends the Act, the
// face moves the file over the VFS and answers Acted, and Files shows it where it went.
import { flushSync, mount } from 'svelte';
import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import fixture from '../../../../contracts/thalamus-shell.fixture.json';
import { fakeTransport } from '$lib/iris/transport.fake';
import type { ToShell } from '$lib/iris/wire';
import IrisApp from '$lib/apps/native/IrisApp.svelte';
import NativeHost from '$lib/components/NativeHost.svelte';
import { _resetRegistry, registerBuiltinNativeApps } from '$lib/apps/native/registry';
import { windows, _reset } from '$lib/stores/desktop';
import { dispatch } from './dispatch';
import type { Limb } from './types';

const fx = fixture as unknown as { to_shell: { case: string; msg: ToShell }[] };
const card = fx.to_shell.find((c) => c.case === 'an action awaits approval')!.msg as Extract<
	ToShell,
	{ t: 'approval_request' }
>;

/** The person's tree on the VFS stub: dir → names (a trailing `/` marks a folder). */
let tree: Record<string, string[]>;
let moves: { src: string; dst: string }[];

function vfs(u: URL, init?: RequestInit): unknown {
	const q = Object.fromEntries(u.searchParams);
	if (u.pathname === '/bff/config') return {};
	if (u.pathname === '/bff/vfs' && q.op === 'list') {
		const names = tree[q.path];
		if (!names) throw new Response('not found', { status: 404 });
		const entries = names.map((n) => {
			const name = n.replace(/\/$/, '');
			return {
				name,
				path: `${q.path}/${name}`,
				kind: n.endsWith('/') ? 'dir' : 'file',
				size: 3,
				mtime: 0
			};
		});
		return { entries };
	}
	if (u.pathname === '/bff/vfs' && init?.method === 'POST') {
		const b = JSON.parse(String(init.body));
		if (b.op !== 'move') throw new Error(`unexpected op ${b.op}`);
		moves.push({ src: b.src, dst: b.dst });
		const cut = (p: string) => [p.slice(0, p.lastIndexOf('/')), p.slice(p.lastIndexOf('/') + 1)];
		const [from, name] = cut(b.src);
		const [to] = cut(b.dst);
		tree[from] = tree[from].filter((n) => n !== name);
		tree[to] = [...tree[to], name];
		return { ok: true };
	}
	throw new Error(`unexpected ${u}`);
}

const settle = async () => {
	for (let i = 0; i < 20; i++) await Promise.resolve();
	flushSync();
};
const top = () => get(windows).reduce((a, b) => (b.z > a.z ? b : a)).app;

beforeEach(() => {
	_reset();
	_resetRegistry();
	registerBuiltinNativeApps();
	tree = {
		documents: ['report.pdf', 'archive/'],
		'documents/archive': ['old.pdf']
	};
	moves = [];
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: URL | string, init?: RequestInit) => {
			try {
				return new Response(JSON.stringify(vfs(new URL(String(input), location.origin), init)));
			} catch (e) {
				if (e instanceof Response) return e;
				throw e;
			}
		})
	);
	// The card's approve waits until its end was fully in view; the window here shows it all.
	vi.stubGlobal(
		'IntersectionObserver',
		class {
			constructor(private cb: (es: { isIntersecting: boolean }[]) => void) {}
			observe() {
				queueMicrotask(() => this.cb([{ isIntersecting: true }]));
			}
			disconnect() {}
		}
	);
});

afterEach(() => {
	document.body.replaceChildren();
	vi.unstubAllGlobals();
});

describe('limbs · files.move, card to what the person sees', () => {
	it('approve → Act → the VFS moves it → Acted ok → Files shows it in archive', async () => {
		const fake = fakeTransport();
		mount(IrisApp, { target: document.body, props: { transport: fake.transport } });
		await settle();
		const limbs = fake.sent.find((m) => m.t === 'limbs') as { limbs: Limb[] };
		expect(limbs.limbs).toContainEqual(
			expect.objectContaining({ app: 'files', action: 'move', writes: true })
		);

		const params = { path: 'documents/report.pdf', to: 'documents/archive' };
		const { says } = limbs.limbs.find((l) => l.app === 'files' && l.action === 'move')!;
		fake.shell({
			...card,
			component: { kind: 'action_approval', props: { app: 'files', action: 'move', params, says } }
		});
		await settle();
		const shown = document.querySelector(`[data-approval="${card.approval}"]`)!;
		expect(shown.textContent).toContain('documents/archive');
		expect(moves).toEqual([]); // nothing moves on the card alone
		[...shown.querySelectorAll('button')].find((b) => b.textContent?.trim() === 'approve')!.click();
		await settle();
		expect(fake.sent).toContainEqual(
			expect.objectContaining({
				t: 'approval_decision',
				approval: card.approval,
				decision: 'approve'
			})
		);

		fake.shell({
			t: 'act',
			session: card.session,
			act: 'mv-1',
			app: 'files',
			action: 'move',
			params
		});
		await vi.waitFor(() =>
			expect(fake.sent).toContainEqual(
				expect.objectContaining({ t: 'acted', act: 'mv-1', ok: true })
			)
		);
		expect(moves).toEqual([{ src: 'documents/report.pdf', dst: 'documents/archive/report.pdf' }]);

		expect(top()).toBe('files');
		const files = document.createElement('div');
		document.body.append(files);
		mount(NativeHost, { target: files, props: { app: 'files' } });
		await vi.waitFor(() => {
			flushSync();
			expect(files.querySelector('.crumbs')?.textContent).toContain('archive');
			expect(files.querySelector('.entry.sel')?.textContent).toContain('report.pdf');
		});
	});

	it('refuses, with a reason and no move, what it must not do', async () => {
		const no = async (path: string, to: string) => {
			const r = await dispatch({ act: 'x', app: 'files', action: 'move', params: { path, to } });
			expect(r.ok).toBe(false);
			return r.reason ?? '';
		};
		expect(await no('documents/missing.pdf', 'documents/archive')).toMatch(/no such file/);
		tree.documents.push('old.pdf');
		expect(await no('documents/old.pdf', 'documents/archive')).toMatch(/already exists/);
		expect(await no('documents/report.pdf', 'documents/nowhere')).toMatch(/no such folder/);
		expect(await no('documents/report.pdf', '../other-user/documents')).toMatch(
			/outside your files/
		);
		expect(await no('documents/../../etc/passwd', 'documents/archive')).toMatch(
			/outside your files/
		);
		expect(await no('/etc/passwd', 'documents/archive')).toMatch(/outside your files/);
		expect(await no('documents/archive', 'documents/archive')).toMatch(/into itself/);
		expect(moves).toEqual([]);
		expect(get(windows)).toEqual([]);
	});
});
