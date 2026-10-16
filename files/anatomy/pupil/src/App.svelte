<!--
  The pupil: the person's workspaces (tabs of widgets on a grid) under one floating chat onto
  the thalamus. The webview holds no socket and no secret; the Rust bridge owns
  ~/.nos/thalamus.sock and emits `to_shell` (decoded) and `link` events, and loads and saves the
  layout (workspace.rs). Window API comes from withGlobalTauri.
-->
<script lang="ts">
	import { onMount, tick } from 'svelte';
	import StatusNote from '$ui/StatusNote.svelte';
	import Tabs from '$ui/Tabs.svelte';
	import AddWidget from './AddWidget.svelte';
	import ApprovalCard from './ApprovalCard.svelte';
	import Chat from './Chat.svelte';
	import Eye from './Eye.svelte';
	import { SETTLE_MS, eye, look, step, type Input } from './eye';
	import Message from './Message.svelte';
	import { asked, closed, composerOpen, decide, empty, seen, type Decision } from './approvals';
	import { forCommand } from './scope';
	import type { DashboardProps, Link, ToShell, ToThalamus, WidgetSpec } from './wire';
	import { route, submit, type Widgets } from './widgets';
	import WorkspaceView from './Workspace.svelte';
	import * as ws from './workspace';

	type Tauri = {
		core: { invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown> };
		event: { listen: <T>(ev: string, cb: (e: { payload: T }) => void) => Promise<() => void> };
	};
	const tauri = (globalThis as { __TAURI__?: Tauri }).__TAURI__;

	type Entry = { me: string } | { msg: ToShell } | { note: string };
	let log: Entry[] = $state([]);
	// Each widget's latest answer by token; the layout says where it sits and what it re-runs.
	let widgets: Widgets = $state({});
	let layout: ws.Layout = $state(ws.empty());
	let loaded = $state(false);
	let layoutNote: string | null = $state(null);
	let top = $state('chat');
	let adding = $state(false);
	let now = $state(Date.now());
	let q = $state(empty());
	let link: Link = $state({ state: 'closed', reason: 'not connected yet' });
	// No turn while an approval waits (shell.rs:173); the bridge refuses one anyway.
	const open = $derived(link.state === 'connected' && composerOpen(q));
	let session: string | null = $state(null);
	// Whom the person works for, as serve said it (working_for); null is no wall.
	let scope: string | null = $state(null);
	let draft = $state('');
	let column: HTMLElement | undefined = $state();
	let ey = $state(eye());
	const see = (i: Input) => (ey = step(ey, i));
	// Choices asked and not yet answered, by id; the eye waits on them as on an approval.
	let asking: string[] = $state([]);
	// Waiting wins until the queue is empty (shell.rs:173), whatever the wire last said.
	const view = $derived(look(ey, q.pending.length, asking.length));
	const space = $derived(layout.workspaces.find((s) => s.id === layout.active) ?? layout.workspaces[0]);
	$effect(() => {
		const { state, seq } = ey;
		if (state !== 'said' && state !== 'refused') return;
		const t = setTimeout(() => see({ e: 'settle', seq }), SETTLE_MS[state]);
		return () => clearTimeout(t);
	});
	// Saved a moment after the last change; the bridge checks it against workspace-layout.yml.
	$effect(() => {
		const snap = $state.snapshot(layout);
		if (!loaded || !tauri) return;
		const t = setTimeout(() => {
			tauri.core.invoke('save_layout', { layout: snap }).catch((e) => (layoutNote = `layout not saved: ${e}`));
		}, 300);
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
		const said = forCommand(text);
		if (said === null) return void push({ note: 'not sent: /for <client>, /for personal or /for all' });
		const msg: ToThalamus = said ? { t: 'working_for', scope: said } : { t: 'turn', session, text };
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

	// The person's answer to a choice: answered only once the bridge took it (an approval waiting
	// refuses it); a refused one leaves the card sendable and the eye waiting.
	async function answered(m: Extract<ToThalamus, { t: 'choice_reply' }>): Promise<boolean> {
		try {
			await tauri?.core.invoke('send', { msg: m });
		} catch (e) {
			push({ msg: { t: 'refused', reason: `not sent: ${e}` } });
			return false;
		}
		asking = asking.filter((id) => id !== m.choice);
		push({ me: m.picked.join(', ') });
		return true;
	}

	async function wire(msg: ToThalamus, widget: string) {
		try {
			await tauri?.core.invoke('send', { msg });
		} catch (e) {
			widgets = route(widgets, { t: 'refused', reason: `not sent: ${e}`, widget }, Date.now()) ?? widgets;
		}
	}
	const sendAll = (ms: ToThalamus[]) => ms.forEach((m) => m.t === 'widget' && wire(m, m.widget));

	// The submit is the person's decision (genui Q1); the reducer sends it once while in flight.
	function submitted(m: { form: string; widget: string; values: Record<string, string | number | boolean> }) {
		const r = submit(widgets, m.widget, m);
		widgets = r.w;
		if (r.send) wire(r.send, m.widget);
	}

	// export.rs writes a new file in Downloads; outside Tauri there is nowhere to save, and that is said.
	const exported = async (name: string, csv: string) =>
		tauri ? `saved to ${await tauri.core.invoke('export_csv', { name, csv })}` : 'not saved: no desktop bridge';

	const viewport = () => ({ w: window.innerWidth, h: window.innerHeight });
	const setChat = (c: ws.Chat) => (layout = { ...layout, chat: ws.clampChat(c, viewport()) });

	function showTab(tab: string) {
		const r = ws.show(layout, widgets, tab);
		layout = r.layout;
		widgets = r.w;
		sendAll(r.send);
	}

	const newId = () => `w${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

	function place(r: { layout: ws.Layout; w: Widgets; send: ToThalamus | null }) {
		if (!r.send) {
			layoutNote = `a workspace holds at most ${ws.MAX_WIDGETS} widgets`;
			return;
		}
		layout = r.layout;
		widgets = r.w;
		adding = false;
		sendAll([r.send]);
	}

	const added = (title: string, spec: WidgetSpec) => place(ws.placed(layout, widgets, newId(), title, spec));

	// The person's click on "Připnout na plochu"; the model has no message that adds a widget.
	function pinned(m: ToShell) {
		place(ws.pin(layout, widgets, newId(), m));
	}

	// The person's click on "Place on a new tab"; the model has no message that places or runs one.
	function placedOffer(d: DashboardProps): boolean {
		const r = ws.placeOffer(layout, widgets, `ws${Date.now().toString(36)}`, d, newId);
		if (!r.send.length) {
			layoutNote = `at most ${ws.MAX_SPACES} tabs: close one to place this dashboard`;
			return false;
		}
		layout = r.layout;
		widgets = r.w;
		sendAll(r.send);
		return true;
	}

	function relens(i: number, value: string) {
		const r = ws.setLens(layout, layout.active, i, value);
		layout = r.layout;
		sendAll(r.send);
	}

	function rerun(id: string) {
		const box = space.widgets.find((b) => b.id === id);
		if (box) sendAll([{ t: 'widget', widget: id, spec: ws.lensed(box.spec, space.lens), trigger: 'click' }]);
	}

	function removed(id: string) {
		layout = ws.removeWidget(layout, id);
		const { [id]: _, ...rest } = widgets;
		widgets = rest;
	}

	function newTab() {
		const n = layout.workspaces.length + 1;
		layout = ws.addSpace(layout, `ws${Date.now().toString(36)}`, `Workspace ${n}`);
	}

	async function loadLayout() {
		try {
			layout = (await tauri?.core.invoke('load_layout')) as ws.Layout;
		} catch (e) {
			layout = ws.empty();
			layoutNote = `${e}; starting with one empty workspace`;
		}
		layout = { ...layout, chat: ws.clampChat(layout.chat, viewport()) };
		loaded = true;
	}

	onMount(() => {
		const tickAge = setInterval(() => (now = Date.now()), 1000);
		const onResize = () => setChat(layout.chat);
		window.addEventListener('resize', onResize);
		if (!tauri) {
			link = { state: 'closed', reason: 'no Tauri bridge (opened outside the pupil app)' };
			loaded = true;
			return () => (clearInterval(tickAge), window.removeEventListener('resize', onResize));
		}
		const off = [
			tauri.event.listen<ToShell>('to_shell', ({ payload }) => {
				see({ e: 'wire', msg: payload });
				if (payload.t === 'session') session = payload.session;
				if (payload.t === 'working_for') scope = payload.scope === 'all' ? null : payload.name;
				// A write landed: the active tab re-runs what read that table, the others go stale.
				if (payload.t === 'table_changed') {
					const r = ws.onTableChanged(layout, widgets, payload.table);
					widgets = r.w;
					sendAll(r.send);
					return;
				}
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
				if (payload.t === 'approval_request') {
					q = asked(q, payload);
					// The card lives in the chat: it opens and comes to the top.
					const r = ws.approvalArrived(layout);
					setChat(r.layout.chat);
					top = r.top;
				} else {
					if (payload.t === 'render' && payload.component.kind === 'choice' && payload.component.props.id)
						asking = [...asking, payload.component.props.id];
					push({ msg: payload });
				}
			}),
			tauri.event.listen<Link>('link', ({ payload }) => {
				link = payload;
				see({ e: 'link', state: payload.state });
				// Connected: the active tab's widgets run as restore; the others when their tab is shown.
				if (payload.state === 'connected') {
					const r = ws.restore(layout);
					widgets = r.w;
					sendAll(r.send);
					return;
				}
				const r = closed(q);
				q = r.q;
				// The session is gone, and its choices with it.
				asking = [];
				r.notes.forEach((note) => push({ note }));
			})
		];
		// The layout first, so a restore on connect has its specs; listen before connect, or the first `link` is missed.
		loadLayout().then(() => Promise.all(off)).then(connect);
		return () => {
			clearInterval(tickAge);
			window.removeEventListener('resize', onResize);
			off.forEach((p) => p.then((f) => f()));
		};
	});
</script>

<main>
	<nav class="bar">
		<Tabs
			tabs={layout.workspaces.map((s) => ({ key: s.id, label: s.name }))}
			bind:active={() => layout.active, (v) => showTab(v)}
			label="Workspaces"
		/>
		<button class="ghost" onclick={newTab} disabled={layout.workspaces.length >= ws.MAX_SPACES} aria-label="add a workspace">+ tab</button>
		{#if layout.workspaces.length > 1}
			<button class="ghost" onclick={() => (layout = ws.removeSpace(layout, layout.active))} aria-label="close this workspace">close tab</button>
		{/if}
		<button onclick={() => (adding = !adding)} aria-expanded={adding}>+ widget</button>
	</nav>
	{#if layoutNote}<StatusNote kind="error" block={false}>{layoutNote}</StatusNote>{/if}
	{#if adding}<AddWidget onadd={added} oncancel={() => (adding = false)} />{/if}
	<WorkspaceView
		{space}
		{widgets}
		{now}
		{top}
		onplace={(id, g) => (layout = ws.setBox(layout, id, g))}
		ontop={(id) => (top = id)}
		onrerun={rerun}
		onremove={removed}
		onsubmit={submitted}
		onlens={relens}
		onexport={exported}
	/>
</main>

<Chat chat={layout.chat} top={top === 'chat'} onchat={setChat} ontop={() => (top = 'chat')}>
	{#snippet head()}
		<span class="dot" class:on={link.state === 'connected'}></span>
		Iris
		{#if scope}<span class="for">for {scope}</span>{/if}
		{#if link.state === 'closed'}
			<StatusNote kind="unwired" block={false}>{link.reason ?? 'disconnected'}</StatusNote>
			<button onclick={connect}>connect</button>
		{/if}
	{/snippet}
	<Eye {view} />
	<div class="column" bind:this={column}>
		{#each log as e}
			{#if 'me' in e}<p class="me">{e.me}</p>
			{:else if 'note' in e}<StatusNote kind="error" block={false}>{e.note}</StatusNote>
			{:else}<Message msg={e.msg} onpin={pinned} onchoose={answered} onplace={placedOffer} />{/if}
		{/each}
	</div>
	{#if q.pending[0]}
		<!-- A fresh card per id: a reused scroll box could show the next edit's end first. -->
		{#key q.pending[0].approval}
		<ApprovalCard
			waiting={q.pending[0]}
			of={q.pending.length}
			whole={q.whole === q.pending[0].approval}
			{scope}
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
</Chat>

<style>
	main {
		min-height: 100vh;
		overflow-y: auto;
	}
	.bar {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 10px 16px 0;
	}
	.bar :global([role='tablist']) {
		flex: 1;
		overflow-x: auto;
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
	.for {
		font-size: 11px;
		border: 1px solid var(--glass-brd);
		border-radius: 6px;
		padding: 0 6px;
	}
	.column {
		flex: 1;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: 12px;
		padding: 8px 16px;
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
		margin: 8px 12px 12px;
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
	button.ghost {
		background: none;
		color: var(--muted);
	}
	button:disabled {
		opacity: 0.4;
	}
</style>
