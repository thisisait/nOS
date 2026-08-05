<!--
  FilePicker — the file-picker-as-a-service HOST + dialog.

  Mount ONCE in the shell (e.g. in +page.svelte, next to the desktop). It stays
  invisible until `openFilePicker(opts)` (or the postMessage bridge) sets an
  active request, then renders a modal with two modes:
    • from nOS   — browse the VFS and pick a path
    • from device — upload a local file INTO the VFS (returns the new path)

  Safety: every displayed name is rendered as escaped text ({name}); there is no
  {@html} anywhere. uid is server-pinned in the BFF — this component never sees it.
-->
<script lang="ts">
	import { activePicker, settlePicker, type PickerRequest } from './service';
	import { CANCELLED } from './types';
	import { vfsList, vfsUpload, type VfsEntry } from '$lib/api/vfs';
	import { crumbs, joinPath, basename } from '../paths';
	import { Tabs, StatusNote, type TabSpec } from '$lib/components/ui';

	let req = $state<PickerRequest | null>(null);
	let mode = $state<'nos' | 'device'>('nos');

	// "From device" only exists when the caller allows an upload, so the tab
	// list is derived rather than fixed — <Tabs> arrow-keys over whatever it is
	// given, so a two-item and a one-item strip both behave correctly.
	const sourceTabs = $derived<TabSpec[]>(
		req?.opts.allowUpload
			? [
					{ key: 'nos', label: 'From nOS' },
					{ key: 'device', label: 'From device' }
				]
			: [{ key: 'nos', label: 'From nOS' }]
	);
	let cwd = $state('documents');
	let entries = $state<VfsEntry[]>([]);
	let selected = $state<VfsEntry | null>(null);
	let loading = $state(false);
	let busy = $state(false);
	let err = $state('');
	let lastId = -1;

	// Pick up a new request from the service store and reset dialog state once.
	$effect(() => {
		const cur = $activePicker;
		req = cur;
		if (cur && cur.id !== lastId) {
			lastId = cur.id;
			mode = 'nos';
			selected = null;
			err = '';
			void load(cur.opts.startPath ?? 'documents');
		}
		if (!cur) lastId = -1;
	});

	async function load(path: string) {
		loading = true;
		err = '';
		try {
			entries = await vfsList(path);
			cwd = path;
			selected = null;
		} catch (e) {
			err = e instanceof Error ? e.message : 'failed to list folder';
			entries = [];
		} finally {
			loading = false;
		}
	}

	function onRow(entry: VfsEntry) {
		if (entry.kind === 'dir') void load(joinPath(cwd, entry.name));
		else selected = selected?.path === entry.path ? null : entry;
	}

	function cancel() {
		if (req) settlePicker(req, CANCELLED);
	}

	function confirmFile() {
		if (!req || !selected) return;
		settlePicker(req, {
			ok: true,
			mode: 'nos',
			path: joinPath(cwd, selected.name),
			name: selected.name,
			kind: 'file'
		});
	}

	function confirmFolder() {
		if (!req) return;
		settlePicker(req, {
			ok: true,
			mode: 'nos',
			path: cwd,
			name: basename(cwd) || 'home',
			kind: 'dir'
		});
	}

	async function onUpload(e: Event) {
		const input = e.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		if (!file || !req) return;
		busy = true;
		err = '';
		try {
			const saved = await vfsUpload(req.opts.uploadDir ?? 'inbox', file);
			settlePicker(req, {
				ok: true,
				mode: 'device',
				path: saved.path,
				name: saved.name,
				kind: 'file'
			});
		} catch (ex) {
			err = ex instanceof Error ? ex.message : 'upload failed';
		} finally {
			busy = false;
			input.value = '';
		}
	}
</script>

{#if req}
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="backdrop" onclick={cancel}>
		<div
			class="dialog glass"
			role="dialog"
			aria-modal="true"
			tabindex="-1"
			aria-label={req.opts.title ?? 'Choose a file'}
			onclick={(e) => e.stopPropagation()}
		>
			<header class="head">
				<strong>{req.opts.title ?? 'Choose a file'}</strong>
				<button class="x" aria-label="Cancel" onclick={cancel}>✕</button>
			</header>

			<div class="tabwrap">
				<Tabs tabs={sourceTabs} bind:active={mode} label="File source" />
			</div>

			{#if err}<StatusNote kind="error" block={false}>{err}</StatusNote>{/if}

			{#if mode === 'nos'}
				<div class="crumbs">
					{#each crumbs(cwd) as c, i (c.path)}
						{#if i > 0}<span class="sep">›</span>{/if}
						<button class="crumb" onclick={() => load(c.path)}>{c.name}</button>
					{/each}
				</div>

				<ul class="list">
					{#if loading}
						<li class="muted">loading…</li>
					{:else if entries.length === 0}
						<li class="muted">empty folder</li>
					{/if}
					{#each entries as entry (entry.path)}
						<li>
							<button
								class="entry"
								class:sel={selected?.path === entry.path}
								onclick={() => onRow(entry)}
							>
								<span class="ico">{entry.kind === 'dir' ? '📁' : '📄'}</span>
								<span class="name">{entry.name}</span>
								{#if entry.kind === 'file'}<span class="size">{entry.size} B</span>{/if}
							</button>
						</li>
					{/each}
				</ul>

				<footer class="foot">
					{#if req.opts.allowDirectories}
						<button class="ghost" onclick={confirmFolder}>Pick this folder</button>
					{/if}
					<span class="spacer"></span>
					<button class="ghost" onclick={cancel}>Cancel</button>
					<button class="primary" disabled={!selected} onclick={confirmFile}>Choose</button>
				</footer>
			{:else}
				<div class="device">
					<p class="muted">
						Upload a file from your device into <code>{req.opts.uploadDir ?? 'inbox'}</code>.
					</p>
					<label class="uploader">
						<input type="file" onchange={onUpload} disabled={busy} />
						<span>{busy ? 'uploading…' : 'Choose a file to upload'}</span>
					</label>
					<footer class="foot">
						<span class="spacer"></span>
						<button class="ghost" onclick={cancel}>Cancel</button>
					</footer>
				</div>
			{/if}
		</div>
	</div>
{/if}

<style>
	.backdrop {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.45);
		display: grid;
		place-items: center;
		z-index: 9000;
	}
	.dialog {
		width: min(560px, 92vw);
		max-height: 80vh;
		display: flex;
		flex-direction: column;
		border-radius: 14px;
		overflow: hidden;
	}
	.head {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 12px 14px;
		border-bottom: 1px solid var(--glass-brd);
	}
	.head strong {
		flex: 1;
		font-size: 14px;
	}
	.x {
		background: none;
		border: none;
		color: var(--muted);
		cursor: pointer;
	}
	/* The private tab strip is gone — it was a row of buttons with no ARIA at
	   all, so assistive tech saw two unrelated controls and the keyboard needed
	   a Tab press per source. <Tabs> is the real pattern. */
	.tabwrap {
		padding: 10px 14px 0;
	}
	.crumbs {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 4px;
		padding: 10px 14px;
		font-size: 12px;
	}
	.crumb {
		background: none;
		border: none;
		color: var(--fg);
		cursor: pointer;
		padding: 2px 4px;
	}
	.sep {
		color: var(--muted);
	}
	.list {
		list-style: none;
		margin: 0;
		padding: 0 8px;
		overflow: auto;
		flex: 1;
		min-height: 140px;
	}
	.entry {
		width: 100%;
		display: flex;
		align-items: center;
		gap: 10px;
		background: none;
		border: none;
		color: var(--fg);
		padding: 7px 8px;
		border-radius: 8px;
		cursor: pointer;
		text-align: left;
	}
	.entry:hover {
		background: rgba(255, 255, 255, 0.06);
	}
	.entry.sel {
		background: rgba(90, 150, 255, 0.25);
	}
	.name {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.size {
		color: var(--muted);
		font-size: 11px;
	}
	.foot {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 12px 14px;
		border-top: 1px solid var(--glass-brd);
	}
	.spacer {
		flex: 1;
	}
	.device {
		padding: 14px;
		display: flex;
		flex-direction: column;
		gap: 12px;
	}
	.uploader {
		display: flex;
		flex-direction: column;
		gap: 8px;
		border: 1px dashed var(--glass-brd);
		border-radius: 10px;
		padding: 18px;
		text-align: center;
		cursor: pointer;
	}
	.primary {
		background: #3268ff;
		color: #fff;
		border: none;
		padding: 7px 14px;
		border-radius: 8px;
		cursor: pointer;
	}
	.primary:disabled {
		opacity: 0.5;
		cursor: default;
	}
	.ghost {
		background: rgba(255, 255, 255, 0.08);
		color: var(--fg);
		border: none;
		padding: 7px 14px;
		border-radius: 8px;
		cursor: pointer;
	}
	.muted {
		color: var(--muted);
	}
	/* .err removed — the third private shade of red in the shell, now StatusNote. */
</style>
