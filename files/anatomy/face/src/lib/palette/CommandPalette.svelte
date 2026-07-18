<!--
  CommandPalette — the Ctrl+Space (hold ≥2s) launcher / mini-terminal.

  Two capabilities, one box:
    • ACTIONS — fuzzy-launch apps + shell actions (Control Panel, Split…). The
      host passes these as `actions`; the palette never invents them.
    • ASK — free text (or a leading "?") goes to the host-local LLM via /bff/ask
      (Ollama MLX, loopback). The answer renders inline, escaped ({text}), never
      {@html}. Running arbitrary HOST COMMANDS is intentionally NOT here — that
      needs a gated, allowlisted, audited Bone endpoint (safety doctrine).

  Trigger: hold Ctrl+Space for 2s (a fill indicator shows the hold). Esc closes.
-->
<script lang="ts">
	import { ask as askLLM, type AskResult } from '$lib/api/ask';

	export interface PaletteAction {
		id: string;
		title: string;
		hint?: string;
		icon?: string;
		run: () => void;
	}

	let { actions = [] as PaletteAction[] }: { actions?: PaletteAction[] } = $props();

	let open = $state(false);
	let holding = $state(false);
	let query = $state('');
	let selected = $state(0);
	let input = $state<HTMLInputElement | null>(null);

	// LLM state.
	let asking = $state(false);
	let answer = $state('');
	let answerNote = $state('');
	let answerModel = $state('');

	let holdTimer: ReturnType<typeof setTimeout> | null = null;

	// Subsequence fuzzy match (order-preserving) — cheap + good enough for a launcher.
	function matches(title: string, q: string): boolean {
		if (!q) return true;
		const t = title.toLowerCase();
		let i = 0;
		for (const ch of q.toLowerCase()) {
			i = t.indexOf(ch, i);
			if (i === -1) return false;
			i += 1;
		}
		return true;
	}

	const filtered = $derived(
		query.startsWith('?') ? [] : actions.filter((a) => matches(a.title, query.trim())).slice(0, 8)
	);

	function reset() {
		query = '';
		selected = 0;
		asking = false;
		answer = '';
		answerNote = '';
		answerModel = '';
	}
	function show() {
		open = true;
		reset();
		queueMicrotask(() => input?.focus());
	}
	function hide() {
		open = false;
	}

	function runAction(a: PaletteAction) {
		hide();
		a.run();
	}

	async function runAsk(prompt: string) {
		const p = prompt.replace(/^\?\s*/, '').trim();
		if (!p) return;
		asking = true;
		answer = '';
		answerNote = '';
		try {
			const res: AskResult = await askLLM(p);
			if (res.configured) {
				answer = res.answer ?? '';
				answerModel = res.model ?? '';
			} else {
				answerNote = res.note ?? 'The local LLM is not configured.';
			}
		} catch (e) {
			answerNote = e instanceof Error ? e.message : 'ask failed';
		} finally {
			asking = false;
		}
	}

	function onEnter() {
		const q = query.trim();
		if (!q) return;
		if (query.startsWith('?') || filtered.length === 0) {
			void runAsk(q);
			return;
		}
		const a = filtered[selected] ?? filtered[0];
		if (a) runAction(a);
	}

	function onPaletteKey(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.preventDefault();
			hide();
		} else if (e.key === 'ArrowDown') {
			e.preventDefault();
			selected = Math.min(selected + 1, Math.max(0, filtered.length - 1));
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			selected = Math.max(selected - 1, 0);
		} else if (e.key === 'Enter') {
			e.preventDefault();
			onEnter();
		}
	}

	// ── Global hold-to-open trigger (Ctrl+Space ≥2s) ────────────────────────────
	function onWinKeyDown(e: KeyboardEvent) {
		if (open) return;
		if (e.ctrlKey && (e.code === 'Space' || e.key === ' ')) {
			e.preventDefault();
			if (holding || holdTimer) return;
			holding = true;
			holdTimer = setTimeout(() => {
				holding = false;
				holdTimer = null;
				show();
			}, 2000);
		}
	}
	function cancelHold() {
		if (holdTimer) clearTimeout(holdTimer);
		holdTimer = null;
		holding = false;
	}
	function onWinKeyUp(e: KeyboardEvent) {
		if (e.code === 'Space' || e.key === ' ' || e.key === 'Control') cancelHold();
	}
</script>

<svelte:window onkeydown={onWinKeyDown} onkeyup={onWinKeyUp} onblur={cancelHold} />

{#if holding}
	<div class="hold" aria-hidden="true">
		<span class="fill"></span>
		<span class="lbl">Keep holding Ctrl+Space…</span>
	</div>
{/if}

{#if open}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<div class="scrim" onclick={hide}></div>
	<div
		class="palette glass"
		role="dialog"
		aria-label="Command palette"
		tabindex="-1"
		onkeydown={onPaletteKey}
	>
		<input
			bind:this={input}
			bind:value={query}
			class="q"
			placeholder="Search apps, run an action, or ask the AI (prefix ?)…"
			spellcheck="false"
			autocomplete="off"
		/>

		{#if !query.startsWith('?') && filtered.length > 0}
			<ul class="results">
				{#each filtered as a, i (a.id)}
					<li>
						<button class="row" class:sel={i === selected} onclick={() => runAction(a)}>
							<span class="ico">{(a.icon ?? '▷').slice(0, 2)}</span>
							<span class="t">{a.title}</span>
							{#if a.hint}<span class="hint">{a.hint}</span>{/if}
						</button>
					</li>
				{/each}
			</ul>
		{/if}

		{#if query.trim()}
			<button class="ask-row" onclick={() => runAsk(query)} disabled={asking}>
				<span class="ico">✦</span>
				<span class="t">Ask nOS AI: “{query.replace(/^\?\s*/, '')}”</span>
			</button>
		{/if}

		{#if asking}
			<div class="answer muted">Thinking…</div>
		{:else if answer}
			<div class="answer">
				<pre>{answer}</pre>
				{#if answerModel}<span class="model">{answerModel}</span>{/if}
			</div>
		{:else if answerNote}
			<div class="answer muted">{answerNote}</div>
		{/if}
	</div>
{/if}

<style>
	.hold {
		position: fixed;
		bottom: 70px;
		left: 50%;
		transform: translateX(-50%);
		z-index: 200001;
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 8px 16px;
		border-radius: 999px;
		background: rgba(20, 24, 40, 0.85);
		overflow: hidden;
	}
	.hold .fill {
		position: absolute;
		inset: 0;
		background: rgba(90, 150, 255, 0.35);
		transform-origin: left;
		animation: fill 2s linear forwards;
	}
	.hold .lbl {
		position: relative;
		font-size: 12px;
		color: #fff;
	}
	@keyframes fill {
		from {
			transform: scaleX(0);
		}
		to {
			transform: scaleX(1);
		}
	}
	.scrim {
		position: fixed;
		inset: 0;
		z-index: 200000;
		background: rgba(0, 0, 0, 0.35);
	}
	.palette {
		position: fixed;
		top: 18vh;
		left: 50%;
		transform: translateX(-50%);
		width: min(620px, 92vw);
		z-index: 200001;
		border-radius: 16px;
		padding: 10px;
		display: flex;
		flex-direction: column;
		gap: 8px;
		box-shadow: 0 24px 70px rgba(0, 0, 0, 0.55);
	}
	.q {
		width: 100%;
		background: rgba(255, 255, 255, 0.06);
		border: 1px solid var(--glass-brd);
		border-radius: 10px;
		padding: 12px 14px;
		color: var(--fg);
		font-size: 15px;
		outline: none;
	}
	.results {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.row,
	.ask-row {
		width: 100%;
		display: flex;
		align-items: center;
		gap: 10px;
		background: none;
		border: none;
		color: var(--fg);
		padding: 9px 10px;
		border-radius: 9px;
		text-align: left;
		cursor: pointer;
		font-size: 13px;
	}
	.row:hover,
	.row.sel,
	.ask-row:hover {
		background: rgba(90, 150, 255, 0.18);
	}
	.ico {
		width: 20px;
		text-align: center;
	}
	.t {
		flex: 1;
	}
	.hint {
		color: var(--muted);
		font-size: 11px;
	}
	.ask-row {
		border-top: 1px solid var(--glass-brd);
		border-radius: 0 0 9px 9px;
	}
	.answer {
		border-top: 1px solid var(--glass-brd);
		padding: 10px;
		max-height: 40vh;
		overflow: auto;
	}
	.answer pre {
		margin: 0;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		font-size: 13px;
		line-height: 1.5;
	}
	.model {
		display: inline-block;
		margin-top: 6px;
		font-size: 11px;
		color: var(--muted);
	}
	.muted {
		color: var(--muted);
	}
</style>
