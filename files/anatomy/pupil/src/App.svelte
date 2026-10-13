<!--
  The pupil: one chat column onto the thalamus. The webview holds no socket and
  no secret; the Rust bridge owns ~/.nos/thalamus.sock and emits `to_shell`
  (decoded) and `link` events. Window API comes from withGlobalTauri.
-->
<script lang="ts">
	import { onMount, tick } from 'svelte';
	import StatusNote from '$ui/StatusNote.svelte';
	import ApprovalCard from './ApprovalCard.svelte';
	import ComponentView from './Component.svelte';
	import Eye from './Eye.svelte';
	import { SETTLE_MS, eye, look, step, type Input } from './eye';
	import Message from './Message.svelte';
	import { asked, closed, composerOpen, decide, empty, seen, type Decision } from './approvals';
	import type { Link, ToShell, ToThalamus } from './wire';
	import { route, type Widgets } from './widgets';

	type Tauri = {
		core: { invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown> };
		event: { listen: <T>(ev: string, cb: (e: { payload: T }) => void) => Promise<() => void> };
	};
	const tauri = (globalThis as { __TAURI__?: Tauri }).__TAURI__;

	type Entry = { me: string } | { msg: ToShell } | { note: string };
	let log: Entry[] = $state([]);
	// Each widget's latest answer by token; the workspace that lays them out is I5h.
	let widgets: Widgets = $state({});
	let q = $state(empty());
	let link: Link = $state({ state: 'closed', reason: 'not connected yet' });
	// No turn while an approval waits (shell.rs:173); the bridge refuses one anyway.
	const open = $derived(link.state === 'connected' && composerOpen(q));
	let session: string | null = $state(null);
	let draft = $state('');
	let column: HTMLElement | undefined = $state();
	let ey = $state(eye());
	const see = (i: Input) => (ey = step(ey, i));
	// Waiting wins until the queue is empty (shell.rs:173), whatever the wire last said.
	const view = $derived(look(ey, q.pending.length));
	$effect(() => {
		const { state, seq } = ey;
		if (state !== 'said' && state !== 'refused') return;
		const t = setTimeout(() => see({ e: 'settle', seq }), SETTLE_MS[state]);
		return () => clearTimeout(t);
	});

	async function push(e: Entry) {
		log.push(e);
		await tick();
		column?.scrollTo({ top: column.scrollHeight });
	}

	async function connect() {
		try {
			await tauri?.core.invoke('connect');
		} catch (e) {
			link = { state: 'closed', reason: String(e) };
		}
	}

	async function send() {
		const text = draft.trim();
		if (!text || !open) return;
		const msg: ToThalamus = { t: 'turn', session, text };
		try {
			await tauri?.core.invoke('send', { msg });
			draft = '';
			push({ me: text });
		} catch (e) {
			push({ msg: { t: 'refused', reason: `not sent: ${e}` } });
		}
	}

	// The decided edit joins the scrollback with the answer, as shell.rs:181-182 does.
	async function decided(approval: string, d: Decision) {
		const r = decide(q, approval, d);
		if (!r.send || !r.decided) return;
		q = r.q;
		push({ msg: { t: 'approval_request', session: session ?? '', ...r.decided } });
		push({ me: d });
		try {
			await tauri?.core.invoke('send', { msg: r.send });
		} catch (e) {
			push({ note: `not decided, nothing written: approval ${approval} (${e})` });
		}
	}

	onMount(() => {
		if (!tauri) {
			link = { state: 'closed', reason: 'no Tauri bridge (opened outside the pupil app)' };
			return;
		}
		const off = [
			tauri.event.listen<ToShell>('to_shell', ({ payload }) => {
				see({ e: 'wire', msg: payload });
				if (payload.t === 'session') session = payload.session;
				const w = route(widgets, payload, Date.now());
				if (w) {
					widgets = w;
					return;
				}
				// The eye shows every phase; the log keeps only a tool run, so the person sees what was called.
				if (payload.t === 'activity') {
					if (typeof payload.phase === 'object') push({ msg: payload });
					return;
				}
				if (payload.t === 'approval_request') q = asked(q, payload);
				else push({ msg: payload });
			}),
			tauri.event.listen<Link>('link', ({ payload }) => {
				link = payload;
				see({ e: 'link', state: payload.state });
				if (payload.state !== 'closed') return;
				const r = closed(q);
				q = r.q;
				r.notes.forEach((note) => push({ note }));
			})
		];
		Promise.all(off).then(connect); // listen first, or the first `link` is missed
		return () => off.forEach((p) => p.then((f) => f()));
	});
</script>

<main>
	<header>
		<span class="dot" class:on={link.state === 'connected'}></span>
		Iris
		{#if link.state === 'closed'}
			<StatusNote kind="unwired" block={false}>{link.reason ?? 'disconnected'}</StatusNote>
			<button onclick={connect}>connect</button>
		{/if}
	</header>
	<Eye {view} />
	{#if Object.keys(widgets).length}
		<section class="widgets">
			{#each Object.entries(widgets) as [token, w] (token)}
				<article class="widget" data-widget={token}>
					{#if w.error}<StatusNote kind="error" block={false}>{w.error}</StatusNote>{/if}
					{#if w.component}<ComponentView component={w.component} />{/if}
				</article>
			{/each}
		</section>
	{/if}
	<div class="column" bind:this={column}>
		{#each log as e}
			{#if 'me' in e}<p class="me">{e.me}</p>
			{:else if 'note' in e}<StatusNote kind="error" block={false}>{e.note}</StatusNote>
			{:else}<Message msg={e.msg} />{/if}
		{/each}
	</div>
	{#if q.pending[0]}
		<!-- A fresh card per id: a reused scroll box could show the next edit's end first. -->
		{#key q.pending[0].approval}
		<ApprovalCard
			waiting={q.pending[0]}
			of={q.pending.length}
			whole={q.whole === q.pending[0].approval}
			onseen={(id) => (q = seen(q, id))}
			ondecide={decided}
		/>
		{/key}
	{/if}
	<form
		class="composer"
		onsubmit={(e) => {
			e.preventDefault();
			send();
		}}
	>
		<textarea
			bind:value={draft}
			rows="2"
			placeholder={q.pending.length ? 'decide the approval first' : 'Ask Iris…'}
			disabled={!open}
			oninput={(e) => see({ e: 'typing', text: e.currentTarget.value })}
			onkeydown={(e) => {
				if (e.key === 'Enter' && !e.shiftKey) {
					e.preventDefault();
					send();
				}
			}}
		></textarea>
		<button type="submit" disabled={!open || !draft.trim()}>send</button>
	</form>
</main>

<style>
	main {
		display: flex;
		flex-direction: column;
		height: 100vh;
		max-width: 860px;
		margin: 0 auto;
	}
	header {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 10px 16px;
		font-weight: 600;
	}
	.dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--muted);
	}
	.dot.on {
		background: var(--ok);
	}
	.column {
		flex: 1;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: 12px;
		padding: 8px 16px;
	}
	.widgets {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
		gap: 8px;
		padding: 0 16px;
	}
	.widget {
		padding: 8px;
		border: 1px solid var(--glass-brd);
		border-radius: 12px;
		background: var(--glass);
	}
	.me {
		align-self: flex-end;
		margin: 0;
		padding: 6px 12px;
		border-radius: 12px;
		background: var(--info-soft);
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	.composer {
		display: flex;
		gap: 8px;
		margin: 8px 16px 16px;
		padding: 8px;
		border: 1px solid var(--glass-brd);
		border-radius: 16px;
		background: var(--glass);
	}
	textarea {
		flex: 1;
		resize: none;
		border: 0;
		background: transparent;
		color: inherit;
		font: inherit;
		outline: none;
	}
	button {
		border: 1px solid var(--glass-brd);
		background: var(--accent);
		color: var(--bg);
		border-radius: 10px;
		padding: 4px 12px;
	}
	button:disabled {
		opacity: 0.4;
	}
</style>
