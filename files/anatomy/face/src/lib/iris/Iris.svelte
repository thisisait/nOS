<!--
  Iris: the person's workspaces (boards nested by path, each a canvas of widgets) under one floating chat onto
  the thalamus. It holds no socket and no secret: everything goes through `transport`
  (transport.ts), which the pupil backs with its Rust bridge and the face with its BFF.
  null is no bridge at all (the pupil's page opened outside the app), and that is said.
  `limbs` and `act` are the face's (contract 8): what Iris may do on its screen, and doing it.
  The pupil hands neither, so it declares no limbs and answers every act no.
-->
<script lang="ts">
	import { onMount, tick } from 'svelte';
	import StatusNote from '$lib/components/ui/StatusNote.svelte';
	import AddWidget from './AddWidget.svelte';
	import ApprovalCard from './ApprovalCard.svelte';
	import Chat from './Chat.svelte';
	import Eye from './Eye.svelte';
	import { SETTLE_MS, eye, look, step, type Input } from './eye';
	import Message from './Message.svelte';
	import ModelPicker from './ModelPicker.svelte';
	import type { Act, Acted, Limb } from '$lib/limbs/types';
	import { asked, closed, composerOpen, decide, empty, seen, type Decision } from './approvals';
	import { mark, type Catalogue } from './marks';
	import { adopt, replayed, type Entry } from './resume';
	import { forCommand, rewall, tabCommand } from './scope';
	import type {
		DashboardProps,
		Link,
		ModelOption,
		Scope,
		ToShell,
		ToThalamus,
		WidgetSpec
	} from './wire';
	import { route, submit, type Widgets } from './widgets';
	import WorkspaceView from './Workspace.svelte';
	import * as ws from './workspace';
	import type { Transport } from './transport';

	let {
		transport,
		limbs,
		act
	}: {
		transport: Transport | null;
		limbs?: () => Limb[];
		act?: (a: Act) => Promise<Acted>;
	} = $props();

	let log: Entry[] = $state([]);
	// The thalamus answered `workspace` on this link: from then on a save goes to it too.
	let held = false;
	// Each widget's latest answer by token; the layout says where it sits and what it re-runs.
	let widgets: Widgets = $state({});
	let layout: ws.Layout = $state(ws.empty());
	let loaded = $state(false);
	// Snapshot<Layout> is too deep for svelte-check to instantiate; the copy is a plain Layout.
	const plain = () => $state.snapshot(layout as unknown) as ws.Layout;
	let layoutNote: string | null = $state(null);
	let top = $state('chat');
	let adding = $state(false);
	// The board the person asked to delete, with everything inside it; nothing goes before the answer.
	let deleting: string | null = $state(null);
	let now = $state(Date.now());
	let q = $state(empty());
	let link: Link = $state({ state: 'closed', reason: 'not connected yet' });
	// No turn while an approval waits (shell.rs:173); the bridge refuses one anyway.
	const open = $derived(link.state === 'connected' && composerOpen(q));
	let session: string | null = $state(null);
	// Whom the person works for, as serve said it (working_for); null is no wall.
	let scope: string | null = $state(null);
	// What the person last set; said again on a new link, whose serve starts with no wall.
	let want: Scope | null = null;
	// The models this session may bind, as serve last offered them (model_options); the header picks.
	let models: ModelOption[] = $state([]);
	let notOffered: string[] = $state([]);
	let draft = $state('');
	// The person's catalogue as serve last sent it; the composer marks the draft against it (marks.ts).
	let catalogue: Catalogue = $state({ tables: [] });
	const pieces = $derived.by(() => {
		const out: { text: string; kind?: string }[] = [];
		let at = 0;
		for (const s of mark(draft, catalogue)) {
			if (s.start > at) out.push({ text: draft.slice(at, s.start) });
			out.push({ text: draft.slice(s.start, s.end), kind: s.kind });
			at = s.end;
		}
		if (at < draft.length) out.push({ text: draft.slice(at) });
		return out;
	});
	let column: HTMLElement | undefined = $state();
	let ey = $state(eye());
	const see = (i: Input) => (ey = step(ey, i));
	// Choices asked and not yet answered, by id; the eye waits on them as on an approval.
	let asking: string[] = $state([]);
	// Waiting wins until the queue is empty (shell.rs:173), whatever the wire last said.
	const view = $derived(look(ey, q.pending.length, asking.length));
	const space = $derived(
		layout.workspaces.find((s) => s.id === layout.active) ?? layout.workspaces[0]
	);
	const nameOf = (id: string) => layout.workspaces.find((s) => s.id === id)?.name ?? id;
	const crumbs = $derived(ws.chain(layout, space.id));
	const roots = $derived(layout.workspaces.filter((s) => !s.parent));
	$effect(() => {
		const { state, seq } = ey;
		if (state !== 'said' && state !== 'refused') return;
		const t = setTimeout(() => see({ e: 'settle', seq }), SETTLE_MS[state]);
		return () => clearTimeout(t);
	});
	// Saved a moment after the last change; the bridge checks it against workspace-layout.yml. The local
	// file is the offline cache; the thalamus's copy is the person's once it answered on this link.
	$effect(() => {
		const snap = plain();
		if (!loaded || !transport) return;
		const t = setTimeout(() => {
			transport.saveLayout(snap).catch((e) => (layoutNote = `layout not saved: ${e}`));
			if (held && link.state === 'connected')
				transport
					.send({ t: 'workspace_save', doc: snap })
					.catch((e) => (layoutNote = `layout not saved to the thalamus: ${e}`));
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
			await transport?.connect();
		} catch (e) {
			link = { state: 'closed', reason: String(e) };
		}
	}

	async function send() {
		const text = draft.trim();
		if (!text || !open) return;
		const said = forCommand(text);
		if (said === null)
			return void push({ note: 'not sent: /for <client>, /for personal or /for all' });
		const tab = tabCommand(text);
		// /branch: a sibling board first, then serve opens its session from this one's conversation.
		const fresh = tab === 'branch' ? `ws${Date.now().toString(36)}` : null;
		const branched = fresh
			? ws.addSpace(layout, fresh, `${space.name} (branch)`, space.parent)
			: layout;
		if (fresh && branched === layout) return void push({ note: `not branched: ${FULL}` });
		const msg: ToThalamus = said
			? { t: 'working_for', scope: said }
			: tab === 'clear'
				? { t: 'clear' }
				: fresh
					? { t: 'branch', workspace: fresh }
					: { t: 'turn', session, text };
		try {
			if (fresh) layout = branched;
			await transport?.send(msg);
			draft = '';
			push({ me: text });
		} catch (e) {
			push({ msg: { t: 'refused', reason: `not sent: ${e}` } });
		}
	}

	// The person's Stop: serve ends the running turn before its next model or tool call (contract 9).
	const busy = $derived(['thinking', 'tool', 'writing'].includes(ey.state));
	function stop() {
		if (session)
			transport?.send({ t: 'stop', session }).catch((e) => push({ note: `not stopped: ${e}` }));
	}

	// Each board is its own conversation: showing another one resumes that board's session.
	function follow(prev: string) {
		if (layout.active === prev || link.state !== 'connected') return;
		transport
			?.send({ t: 'resume', workspace: layout.active })
			.catch((e) => push({ note: `this board's conversation was not resumed: ${e}` }));
	}

	// The decided edit joins the scrollback with the answer, as shell.rs:181-182 does.
	async function decided(approval: string, d: Decision) {
		const r = decide(q, approval, d);
		if (!r.send || !r.decided) return;
		q = r.q;
		push({ msg: { t: 'approval_request', session: session ?? '', ...r.decided } });
		push({ me: d });
		try {
			await transport?.send(r.send);
		} catch (e) {
			push({ note: `not decided, nothing written: approval ${approval} (${e})` });
		}
	}

	// The person's answer to a choice: answered only once the bridge took it (an approval waiting
	// refuses it); a refused one leaves the card sendable and the eye waiting.
	async function answered(m: Extract<ToThalamus, { t: 'choice_reply' }>): Promise<boolean> {
		try {
			await transport?.send(m);
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
			await transport?.send(msg);
		} catch (e) {
			widgets =
				route(widgets, { t: 'refused', reason: `not sent: ${e}`, widget }, Date.now()) ?? widgets;
		}
	}
	const sendAll = (ms: ToThalamus[]) =>
		ms.forEach((m) =>
			m.t === 'widget'
				? wire(m, m.widget)
				: m.t === 'working_for' &&
					transport?.send(m).catch((e) => push({ note: `the scope was not said again: ${e}` }))
		);

	// The submit is the person's decision (genui Q1); the reducer sends it once while in flight.
	function submitted(m: {
		form: string;
		widget: string;
		values: Record<string, string | number | boolean>;
	}) {
		const r = submit(widgets, m.widget, m);
		widgets = r.w;
		if (r.send) wire(r.send, m.widget);
	}

	// The pupil's export.rs writes a new file in Downloads; with no transport there is nowhere to save, and that is said.
	const exported = async (name: string, csv: string) =>
		transport ? `saved to ${await transport.exportCsv(name, csv)}` : 'not saved: no desktop bridge';

	const viewport = () => ({ w: window.innerWidth, h: window.innerHeight });
	const setChat = (c: ws.Chat) => (layout = { ...layout, chat: ws.clampChat(c, viewport()) });

	function showTab(tab: string, prev = layout.active) {
		const r = ws.show(layout, widgets, tab);
		layout = r.layout;
		widgets = r.w;
		sendAll(r.send);
		follow(prev);
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

	const added = (title: string, spec: WidgetSpec) =>
		place(ws.placed(layout, widgets, newId(), title, spec));

	const FULL = `no room for another board here (at most ${ws.MAX_SPACES}, ${ws.MAX_DEPTH} deep, ${ws.MAX_ITEMS} items a board)`;
	const roomy = () => ws.addSpace(layout, 'probe', '', layout.active) !== layout;

	// The person's click on "Sem" or "Nová plocha" under a pin; the model has no message that adds a widget.
	function pinned(m: ToShell, fresh: boolean) {
		if (fresh && !roomy()) return void (layoutNote = `${FULL}: pin here`);
		place(ws.pin(layout, widgets, newId(), m, fresh ? `ws${Date.now().toString(36)}` : undefined));
	}

	// The person's click on "Place here" or "Place on a new board"; the model has no message that places or runs one.
	function placedOffer(d: DashboardProps, here: boolean): boolean {
		const r = ws.placeOffer(layout, widgets, `ws${Date.now().toString(36)}`, d, newId, here);
		if (!r.send.length) {
			layoutNote = here
				? `a workspace holds at most ${ws.MAX_WIDGETS} widgets: place it on a new board`
				: FULL;
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
		const box = ws.widgetsOf(space).find((b) => b.id === id);
		if (box)
			sendAll([
				{ t: 'widget', widget: id, spec: ws.lensed(box.spec, space.lens), trigger: 'click' }
			]);
	}

	function removed(id: string) {
		const card = space.items.find((i) => i.id === id);
		if (card?.kind === 'board') return void (deleting = card.board);
		layout = ws.removeItem(layout, id);
		const rest = { ...widgets };
		delete rest[id];
		widgets = rest;
	}

	function addItem(kind: 'heading' | 'frame') {
		const next = ws.addItem(layout, newId(), kind);
		if (next === layout) layoutNote = `a workspace holds at most ${ws.MAX_ITEMS} items`;
		layout = next;
	}

	// "+ board": a card here that opens a new child; this board stays shown.
	function addBoard() {
		const next = ws.addSpace(layout, `ws${Date.now().toString(36)}`, 'Board', layout.active);
		if (next === layout) layoutNote = FULL;
		else layout = { ...next, active: layout.active };
	}

	function newRoot() {
		const prev = layout.active;
		const next = ws.addSpace(
			layout,
			`ws${Date.now().toString(36)}`,
			`Workspace ${roots.length + 1}`
		);
		if (next === layout) return void (layoutNote = FULL);
		layout = next;
		follow(prev);
	}

	// Yes to the question: the board and its subtree go, their widgets' answers with them.
	function deleteBoard() {
		const prev = layout.active;
		const next = deleting ? ws.removeSpace(layout, deleting) : layout;
		deleting = null;
		if (next === layout) return void (layoutNote = 'the last workspace stays');
		const kept = new Set(next.workspaces.flatMap((s) => ws.widgetsOf(s).map((b) => b.id)));
		widgets = Object.fromEntries(Object.entries(widgets).filter(([k]) => kept.has(k)));
		layout = next;
		showTab(next.active, prev);
	}
	const inside = (id: string) =>
		layout.workspaces.filter((s) => s.id !== id && ws.chain(layout, s.id).includes(id)).length;

	// Escape goes up one board, unless the person is typing or a question is open.
	function escape(e: KeyboardEvent) {
		const t = e.target as HTMLElement;
		if (e.key !== 'Escape' || deleting || !t.closest?.('main')) return;
		if (t.closest('input, textarea, select, [contenteditable]') || !space.parent) return;
		showTab(space.parent);
	}

	async function loadLayout() {
		try {
			layout = ws.migrate((await transport?.loadLayout()) ?? ws.empty());
		} catch (e) {
			layout = ws.empty();
			layoutNote = `${e}; starting with one empty workspace`;
		}
		layout = { ...layout, chat: ws.clampChat(layout.chat, viewport()) };
		loaded = true;
	}

	// The thalamus's workspace, checked and cached by the bridge before it is shown; one it refuses leaves this one.
	async function workspaceHeld(doc: object | null) {
		const r = adopt(plain(), doc);
		held = true;
		if (r.send)
			transport
				?.send(r.send)
				.catch((e) => (layoutNote = `the layout was not moved to the thalamus: ${e}`));
		if (!r.layout || JSON.stringify(r.layout) === JSON.stringify(plain())) return;
		try {
			await transport?.saveLayout(r.layout);
		} catch (e) {
			layoutNote = `the thalamus's layout was refused (${e}); this one is kept`;
			return;
		}
		const prev = layout.active;
		layout = { ...r.layout, chat: ws.clampChat(r.layout.chat, viewport()) };
		// The thalamus's copy may show another tab than this cache did: that tab's conversation, then.
		follow(prev);
		const w = rewall(want, layout, 'working_for');
		widgets = w.w ?? widgets;
		sendAll(w.send);
	}

	// A new link resumes the person's session first, so serve's wall is set again before any widget reads.
	async function linked() {
		// The first failure stops the rest: after a refused hello every later ask fails the same way (live 2026-10-18).
		const say = (msg: ToThalamus, what: string) =>
			transport?.send(msg).then(
				() => true,
				(e) => (push({ note: `${what}: ${e}` }), false)
			);
		if (!(await say({ t: 'resume', workspace: layout.active }, 'the session was not resumed')))
			return;
		if (!(await say({ t: 'workspace_load' }, 'the layout was not asked of the thalamus'))) return;
		await say({ t: 'model_options' }, 'the models were not asked');
		await say({ t: 'catalogue' }, 'the catalogue was not asked, so nothing is marked');
		if (limbs) await say({ t: 'limbs', limbs: limbs() }, 'the limbs were not declared');
		const r = rewall(want, layout, 'connected');
		widgets = r.w ?? widgets;
		sendAll(r.send);
	}

	// An act runs only through the face's dispatch (limbs/dispatch.ts); every outcome is answered, a throw too.
	async function acting(m: Extract<ToShell, { t: 'act' }>) {
		const one: Act = { act: m.act, app: m.app, action: m.action, params: m.params };
		let r: Acted;
		try {
			r = act ? await act(one) : { act: m.act, ok: false, reason: 'this shell has no limbs' };
		} catch (e) {
			r = { act: m.act, ok: false, reason: String(e) };
		}
		transport
			?.send({ t: 'acted', ...r })
			.catch((e) => push({ note: `the act was not answered: ${e}` }));
	}

	onMount(() => {
		const tickAge = setInterval(() => (now = Date.now()), 1000);
		const onResize = () => setChat(layout.chat);
		window.addEventListener('resize', onResize);
		if (!transport) {
			link = {
				state: 'closed',
				reason: 'no bridge to the thalamus (opened outside the pupil app)'
			};
			loaded = true;
			return () => (clearInterval(tickAge), window.removeEventListener('resize', onResize));
		}
		const off = [
			transport.onShell((payload) => {
				see({ e: 'wire', msg: payload });
				// Another session (a tab, /clear, /branch) is another chat; a resumed or branched one replays its own.
				if (payload.t === 'session') {
					if (session && payload.session !== session) log = [];
					session = payload.session;
				}
				if (payload.t === 'model_state') return void see({ e: 'model', loaded: payload.loaded });
				// A resumed session's chat replaces this window's: it is the whole of it, cards still open included.
				if (payload.t === 'replay') {
					const r = replayed(payload);
					log = r.log;
					q = r.q;
					asking = r.asking;
					if (q.pending.length) {
						const a = ws.approvalArrived(layout);
						setChat(a.layout.chat);
						top = a.top;
					}
					return;
				}
				if (payload.t === 'said') return void push({ me: payload.text });
				if (payload.t === 'workspace') return void workspaceHeld(payload.doc);
				if (payload.t === 'catalogue') return void (catalogue = { tables: payload.tables });
				if (payload.t === 'act') return void acting(payload);
				if (payload.t === 'model_options') {
					models = payload.options;
					notOffered = payload.refused;
					return;
				}
				if (payload.t === 'working_for') {
					scope = payload.scope === 'all' ? null : payload.name;
					want = payload.scope === 'all' ? null : payload.scope;
					const r = rewall(want, layout, 'working_for');
					widgets = r.w ?? widgets;
					sendAll(r.send);
				}
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
					if (
						payload.t === 'render' &&
						payload.component.kind === 'choice' &&
						payload.component.props.id
					)
						asking = [...asking, payload.component.props.id];
					push({ msg: payload });
				}
			}),
			transport.onLink((payload) => {
				link = payload;
				see({ e: 'link', state: payload.state });
				// Connected: the active tab's widgets run as restore; the others when their tab is shown.
				if (payload.state === 'connected') return void linked();
				// No link, no wall: the chip waits for serve to say it again; a resumed session runs on the host's model.
				held = false;
				scope = null;
				models = [];
				catalogue = { tables: [] };
				const r = closed(q);
				q = r.q;
				// The session is gone, and its choices with it.
				asking = [];
				r.notes.forEach((note) => push({ note }));
			})
		];
		// The layout first, so a restore on connect has its specs; listen before connect, or the first `link` is missed.
		loadLayout()
			.then(() => Promise.all(off))
			.then(connect);
		return () => {
			clearInterval(tickAge);
			window.removeEventListener('resize', onResize);
			off.forEach((p) => p.then((f) => f()));
		};
	});
</script>

<svelte:window onkeydown={escape} />
<main>
	<div class="bar">
		<nav class="crumbs" aria-label="workspace path" title={ws.pathOf(layout, space.id)}>
			<details>
				<summary aria-label="all workspaces">▾</summary>
				<ul>
					{#each roots as r (r.id)}
						<li><button class="ghost" onclick={() => showTab(r.id)}>{r.name}</button></li>
					{/each}
					<li>
						<button
							class="ghost"
							onclick={newRoot}
							disabled={layout.workspaces.length >= ws.MAX_SPACES}>+ new workspace</button
						>
					</li>
				</ul>
			</details>
			<ol>
				{#each crumbs as id, i (id)}
					<li>
						{#if i < crumbs.length - 1}
							<button class="ghost" onclick={() => showTab(id)}>{nameOf(id)}</button>
						{:else}
							<span aria-current="page">{nameOf(id)}</span>
						{/if}
					</li>
				{/each}
			</ol>
		</nav>
		<button onclick={() => (adding = !adding)} aria-expanded={adding}>+ widget</button>
		<button class="ghost" onclick={() => addItem('heading')}>+ heading</button>
		<button class="ghost" onclick={() => addItem('frame')}>+ frame</button>
		<button class="ghost" onclick={addBoard}>+ board</button>
		{#if space.parent || roots.length > 1}
			<button class="ghost" onclick={() => (deleting = space.id)}>delete board</button>
		{/if}
	</div>
	{#if deleting}
		<p class="ask" role="alert">
			Delete “{nameOf(deleting)}”{inside(deleting)
				? ` and the ${inside(deleting)} boards inside it`
				: ''}?
			<button onclick={deleteBoard}>delete</button>
			<button class="ghost" onclick={() => (deleting = null)}>keep</button>
		</p>
	{/if}
	{#if layoutNote}<StatusNote kind="error" block={false}>{layoutNote}</StatusNote>{/if}
	{#if adding}<AddWidget onadd={added} oncancel={() => (adding = false)} />{/if}
	<WorkspaceView
		{space}
		spaces={layout.workspaces}
		onopen={(id) => showTab(id)}
		{widgets}
		{now}
		{top}
		onplace={(id, g) => (layout = ws.setBox(layout, id, g))}
		ontext={(id, t) => (layout = ws.setText(layout, id, t))}
		onview={(v) => (layout = ws.setView(layout, layout.active, v))}
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
		{#if models.length}
			<ModelPicker
				options={models}
				refused={notOffered}
				onpick={(m) =>
					transport
						?.send(m)
						.catch((e) => push({ msg: { t: 'refused', reason: `not picked: ${e}` } }))}
			/>
		{/if}
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
		<div class="field">
			<!-- The marks sit behind the transparent textarea, which keeps the focus, the text and a11y. -->
			<div class="marks" aria-hidden="true">
				{#each pieces as p}{#if p.kind}<mark data-kind={p.kind}>{p.text}</mark
						>{:else}{p.text}{/if}{/each}{'​'}
			</div>
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
		</div>
		{#if busy && session}<button type="button" onclick={stop}>stop</button>{/if}
		<button type="submit" disabled={!open || !draft.trim()}>send</button>
	</form>
</Chat>

<style>
	main {
		display: flex;
		flex-direction: column;
		height: 100vh;
	}
	.bar {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 10px 16px 0;
	}
	.crumbs {
		flex: 1;
		display: flex;
		align-items: center;
		gap: 4px;
		min-width: 0;
		overflow-x: auto;
	}
	.crumbs ol {
		display: flex;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.crumbs li + li::before {
		content: '/';
		margin: 0 4px;
		color: var(--muted);
	}
	.crumbs [aria-current] {
		font-weight: 600;
	}
	.crumbs details {
		position: relative;
	}
	.crumbs summary {
		cursor: pointer;
		list-style: none;
		color: var(--muted);
	}
	.crumbs ul {
		position: absolute;
		z-index: 10;
		margin: 4px 0 0;
		padding: 4px;
		list-style: none;
		border: 1px solid var(--glass-brd);
		border-radius: 10px;
		background: var(--bg);
	}
	.ask {
		display: flex;
		align-items: center;
		gap: 8px;
		margin: 8px 16px 0;
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
	.field {
		flex: 1;
		display: grid;
	}
	.field > * {
		grid-area: 1 / 1;
		margin: 0;
		padding: 2px;
		font: inherit;
		line-height: 1.4;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	.marks {
		color: transparent;
		pointer-events: none;
		overflow: hidden;
	}
	mark {
		color: transparent;
		border-radius: 4px;
		background: var(--info-soft);
	}
	mark[data-kind='option'] {
		background: var(--ok-soft);
	}
	mark[data-kind='date'],
	mark[data-kind='period'] {
		background: var(--warn-soft);
	}
	mark[data-kind='number'],
	mark[data-kind='operator'] {
		background: none;
		box-shadow: inset 0 -2px var(--muted);
	}
	textarea {
		resize: none;
		border: 0;
		background: transparent;
		color: inherit;
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
