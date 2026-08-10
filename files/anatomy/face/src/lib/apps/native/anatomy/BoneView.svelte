<!--
  Bone view — liveness, the vein the face depends on, and what this view is
  NOT allowed to see.

  The third panel is the one that matters. The face holds a static VFS bearer,
  not an `nos:state:read` JWT, so three of Bone's read surfaces answer 401 to
  it. A view could quietly omit them; that would teach the operator there is
  nothing there. They are rendered as declared gaps instead — the reason on
  screen, not in a comment.

  `status: ok` and `auth_ready: false` can both be true at once, and that
  combination is worth its own line: Bone answers liveness while every
  scope-gated endpoint returns 503. Liveness is all that field ever claimed.
-->
<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { loadBone, type BoneResponse } from '$lib/api/pulse';
	import { humanUptime, type BoneGap } from '$lib/anatomy/bone';
	import { StatusNote, Badge, StateDot, Panel } from '$lib/components/ui';

	let data = $state<BoneResponse | null>(null);
	let err = $state('');
	let loading = $state(true);

	const POLL_MS = 60_000;
	let timer: ReturnType<typeof setInterval> | undefined;

	async function refresh() {
		try {
			data = await loadBone();
			err = '';
		} catch (e) {
			err = e instanceof Error ? e.message : 'could not reach the BFF';
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		void refresh();
		timer = setInterval(() => void refresh(), POLL_MS);
	});
	onDestroy(() => clearInterval(timer));

	const gaps = $derived((data?.gaps ?? []) as BoneGap[]);
</script>

<div class="bone">
	{#if loading}
		<StatusNote kind="loading">Probing Bone…</StatusNote>
	{:else if err}
		<StatusNote kind="error" title="The face BFF did not answer">{err}</StatusNote>
	{:else if data}
		<div class="cards">
			<Panel title="Daemon">
				{#if data.alive}
					<p class="line">
						<StateDot tone="ok" label="responding" />
						<span>answers <code>/api/health</code></span>
						<Badge tone="neutral">up {humanUptime(data.uptimeSeconds ?? null)}</Badge>
					</p>
					<p class="line">
						<StateDot
							tone={data.authReady ? 'ok' : 'bad'}
							label={data.authReady ? 'JWT auth ready' : 'JWT auth not initialised'}
						/>
						<span>
							{#if data.authReady}
								JWT auth initialised
							{:else}
								JWT auth NOT initialised
							{/if}
						</span>
					</p>
					{#if data.authReady === false}
						<StatusNote kind="error" title="Every scope-gated endpoint is answering 503">
							Bone still reports <code>status: ok</code> — liveness is all that field claims. Agents calling
							state, migration or upgrade endpoints are being refused while this screen’s first line stays
							green.
						</StatusNote>
					{/if}
				{:else}
					<StatusNote kind="error" title="Bone did not answer its liveness probe">
						{data.error || 'no response'}
					</StatusNote>
				{/if}
			</Panel>

			<Panel title="Vein · face → Bone VFS">
				<p class="line">
					<StateDot
						tone={data.vfs?.ok ? 'ok' : 'bad'}
						label={data.vfs?.ok ? 'carrying' : 'not carrying'}
					/>
					<span>{data.vfs?.ok ? 'carrying traffic' : 'not carrying'}</span>
				</p>
				<p class="detail">{data.vfs?.detail}</p>
				{#if !data.vfs?.ok}
					<StatusNote kind="error" title="The file browser will degrade quietly">
						Bone can be alive while this fails — a stale or unset
						<code>NOS_VFS_API_TOKEN</code> breaks the vein, not the organ.
					</StatusNote>
				{/if}
			</Panel>
		</div>

		<div class="gaps">
			<Panel title="Not visible from here">
				<p class="intro">
					These are read surfaces this view is not credentialed for. They are listed rather than
					omitted: a panel that shows nothing where it cannot look teaches you there is nothing
					there.
				</p>
				<ul>
					{#each gaps as g (g.endpoint)}
						<li>
							<code>{g.endpoint}</code>
							<span>{g.reason}</span>
						</li>
					{/each}
				</ul>
				<StatusNote kind="unwired" title="To close these">
					mint a face client with the <code>nos:state:read</code> scope, or have Bone expose an ungated
					summary. Until then this view is honest about its reach.
				</StatusNote>
			</Panel>
		</div>
	{/if}
</div>

<style>
	.bone {
		font-size: 13px;
		display: flex;
		flex-direction: column;
		gap: 12px;
	}
	.cards {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 12px;
		align-items: start;
	}
	@media (max-width: 820px) {
		.cards {
			grid-template-columns: 1fr;
		}
	}
	/* .card and h3 removed 2026-08-05 — both are <Panel> now, which is also
	   where the uppercase heading treatment lives. */
	.line {
		display: flex;
		align-items: center;
		gap: 8px;
		margin: 0;
	}
	.detail,
	.intro {
		margin: 0;
		font-size: 11px;
		line-height: 1.6;
		color: var(--muted, #9aa4b2);
	}
	code {
		font-family: ui-monospace, monospace;
		font-size: 11px;
	}
	.gaps ul {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.gaps li {
		display: flex;
		flex-direction: column;
		gap: 2px;
		font-size: 11px;
		padding: 6px 8px;
		border-radius: 6px;
		background: rgba(255, 255, 255, 0.03);
	}
	.gaps li span {
		color: var(--muted, #9aa4b2);
		line-height: 1.5;
	}
</style>
