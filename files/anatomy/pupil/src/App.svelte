<!--
  The pupil: one chat column onto the thalamus. The webview holds no socket and
  no secret; the Rust bridge owns ~/.nos/thalamus.sock and emits `to_shell`
  (decoded) and `link` events. Window API comes from withGlobalTauri.
-->
<script lang="ts">
	import { onMount, tick } from 'svelte';
	import StatusNote from '$ui/StatusNote.svelte';
	import Message from './Message.svelte';
	import type { Link, ToShell, ToThalamus } from './wire';

	type Tauri = {
		core: { invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown> };
		event: { listen: <T>(ev: string, cb: (e: { payload: T }) => void) => Promise<() => void> };
	};
	const tauri = (globalThis as { __TAURI__?: Tauri }).__TAURI__;

	type Entry = { me: string } | { msg: ToShell };
	let log: Entry[] = $state([]);
	let link: Link = $state({ state: 'closed', reason: 'not connected yet' });
	let session: string | null = $state(null);
	let draft = $state('');
	let column: HTMLElement | undefined = $state();

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
		if (!text || link.state !== 'connected') return;
		const msg: ToThalamus = { t: 'turn', session, text };
		try {
			await tauri?.core.invoke('send', { msg });
			draft = '';
			push({ me: text });
		} catch (e) {
			push({ msg: { t: 'refused', reason: `not sent: ${e}` } });
		}
	}

	onMount(() => {
		if (!tauri) {
			link = { state: 'closed', reason: 'no Tauri bridge (opened outside the pupil app)' };
			return;
		}
		const off = [
			tauri.event.listen<ToShell>('to_shell', ({ payload }) => {
				if (payload.t === 'session') session = payload.session;
				push({ msg: payload });
			}),
			tauri.event.listen<Link>('link', ({ payload }) => (link = payload))
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
	<div class="column" bind:this={column}>
		{#each log as e}
			{#if 'me' in e}<p class="me">{e.me}</p>{:else}<Message msg={e.msg} />{/if}
		{/each}
	</div>
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
			placeholder="Ask Iris…"
			disabled={link.state !== 'connected'}
			onkeydown={(e) => {
				if (e.key === 'Enter' && !e.shiftKey) {
					e.preventDefault();
					send();
				}
			}}
		></textarea>
		<button type="submit" disabled={link.state !== 'connected' || !draft.trim()}>send</button>
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
