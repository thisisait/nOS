<!--
  FilesApp — the reference nOS-native app (Tier F1 + VFS).

  A real file browser over the class-3 per-user tree. It CALLS the BFF VFS API
  (list/read/mkdir/delete/upload/download) — it is NOT an iframe. uid is pinned
  server-side; the browser only ever hits same-origin /bff/vfs.

  XSS-safe: all file names + text content render as escaped text ({…} / <pre>{…}),
  never {@html}. This is the hard Wave-2 gate.
-->
<script module lang="ts">
	import type { VfsEntry as _VfsEntry } from '$lib/api/vfs';
	// Auto-refresh cap: a module-scoped last-listing shared across FilesApp
	// (re)mounts. An AUTOMATIC reload (onMount) of the same path within 10s reuses
	// this instead of re-hitting the VFS — so we never spam Bone/FS. User actions
	// (Refresh / navigate / mkdir / delete / upload) always refetch.
	const LOAD_THROTTLE_MS = 10_000;
	let _last: { path: string; entries: _VfsEntry[]; at: number } | null = null;
</script>

<script lang="ts">
	import { onMount } from 'svelte';
	import {
		vfsList,
		vfsRead,
		vfsMkdir,
		vfsDelete,
		vfsUpload,
		vfsDownloadUrl,
		type VfsEntry
	} from '$lib/api/vfs';
	import { crumbs, joinPath } from './paths';

	let cwd = $state('documents');
	let entries = $state<VfsEntry[]>([]);
	let loading = $state(false);
	let err = $state('');
	let selected = $state<VfsEntry | null>(null);
	let preview = $state<string | null>(null);
	let previewErr = $state('');
	let busy = $state(false);

	async function load(path: string, opts: { auto?: boolean } = {}) {
		// Throttle only AUTOMATIC reloads (onMount / remount): reuse a fresh cached
		// listing of the same path rather than re-fetching. Manual calls skip this.
		if (opts.auto && _last && _last.path === path && Date.now() - _last.at < LOAD_THROTTLE_MS) {
			entries = _last.entries;
			cwd = path;
			return;
		}
		loading = true;
		err = '';
		selected = null;
		preview = null;
		previewErr = '';
		try {
			entries = await vfsList(path);
			cwd = path;
			_last = { path, entries, at: Date.now() };
		} catch (e) {
			err = e instanceof Error ? e.message : 'failed to list folder';
			entries = [];
		} finally {
			loading = false;
		}
	}

	onMount(() => void load('documents', { auto: true }));

	async function openEntry(entry: VfsEntry) {
		if (entry.kind === 'dir') {
			void load(joinPath(cwd, entry.name));
			return;
		}
		selected = entry;
		preview = null;
		previewErr = '';
		try {
			preview = await vfsRead(joinPath(cwd, entry.name));
		} catch (e) {
			// Binary / too-large → offer download instead of an inline preview.
			previewErr = e instanceof Error ? e.message : 'cannot preview this file';
		}
	}

	async function newFolder() {
		const name = prompt('New folder name');
		if (!name) return;
		busy = true;
		err = '';
		try {
			await vfsMkdir(joinPath(cwd, name));
			await load(cwd);
		} catch (e) {
			err = e instanceof Error ? e.message : 'mkdir failed';
		} finally {
			busy = false;
		}
	}

	async function removeSelected() {
		if (!selected) return;
		if (!confirm(`Delete ${selected.name}?`)) return;
		busy = true;
		err = '';
		try {
			await vfsDelete(joinPath(cwd, selected.name));
			await load(cwd);
		} catch (e) {
			err = e instanceof Error ? e.message : 'delete failed';
		} finally {
			busy = false;
		}
	}

	async function onUpload(e: Event) {
		const input = e.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return;
		busy = true;
		err = '';
		try {
			await vfsUpload(cwd, file);
			await load(cwd);
		} catch (ex) {
			err = ex instanceof Error ? ex.message : 'upload failed';
		} finally {
			busy = false;
			input.value = '';
		}
	}
</script>

<div class="files">
	<header class="bar">
		<button class="btn" onclick={() => load(cwd)} disabled={busy}>Refresh</button>
		<button class="btn" onclick={newFolder} disabled={busy}>New folder</button>
		<label class="btn upload">
			Upload
			<input type="file" onchange={onUpload} disabled={busy} hidden />
		</label>
		<button class="btn" onclick={removeSelected} disabled={busy || !selected}>Delete</button>
	</header>

	<nav class="crumbs">
		{#each crumbs(cwd) as c, i (c.path)}
			{#if i > 0}<span class="sep">›</span>{/if}
			<button class="crumb" onclick={() => load(c.path)}>{c.name}</button>
		{/each}
	</nav>

	{#if err}<p class="err">{err}</p>{/if}

	<div class="split">
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
						onclick={() => openEntry(entry)}
					>
						<span class="ico">{entry.kind === 'dir' ? '📁' : '📄'}</span>
						<span class="name">{entry.name}</span>
						{#if entry.kind === 'file'}<span class="size">{entry.size} B</span>{/if}
					</button>
				</li>
			{/each}
		</ul>

		<aside class="pane">
			{#if selected}
				<h4>{selected.name}</h4>
				<p class="meta muted">{selected.size} B · {selected.kind}</p>
				<a class="btn dl" href={vfsDownloadUrl(joinPath(cwd, selected.name))} download>Download</a>
				{#if preview !== null}
					<pre class="preview">{preview}</pre>
				{:else if previewErr}
					<p class="muted">{previewErr}</p>
				{:else}
					<p class="muted">loading preview…</p>
				{/if}
			{:else}
				<p class="muted">Select a file to preview.</p>
			{/if}
		</aside>
	</div>
</div>

<style>
	.files {
		display: flex;
		flex-direction: column;
		height: 100%;
		gap: 8px;
	}
	.bar {
		display: flex;
		gap: 6px;
		flex-wrap: wrap;
	}
	.btn {
		background: rgba(255, 255, 255, 0.08);
		color: var(--fg);
		border: none;
		padding: 6px 12px;
		border-radius: 8px;
		cursor: pointer;
		font-size: 12px;
	}
	.btn:disabled {
		opacity: 0.5;
		cursor: default;
	}
	.upload {
		display: inline-flex;
		align-items: center;
	}
	.crumbs {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 4px;
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
	.split {
		display: flex;
		gap: 10px;
		flex: 1;
		min-height: 0;
	}
	.list {
		list-style: none;
		margin: 0;
		padding: 0;
		overflow: auto;
		flex: 1;
		min-width: 0;
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
	.pane {
		width: 44%;
		border-left: 1px solid var(--glass-brd);
		padding-left: 10px;
		overflow: auto;
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.pane h4 {
		margin: 0;
		overflow-wrap: anywhere;
	}
	.dl {
		align-self: flex-start;
		text-decoration: none;
	}
	.preview {
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		background: rgba(0, 0, 0, 0.25);
		padding: 8px;
		border-radius: 8px;
		font-size: 12px;
		margin: 0;
		max-height: 100%;
		overflow: auto;
	}
	.muted {
		color: var(--muted);
	}
	.err {
		color: #ff8080;
		font-size: 12px;
		margin: 0;
	}
</style>
