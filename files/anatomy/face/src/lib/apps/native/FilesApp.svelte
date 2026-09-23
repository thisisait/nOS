<!--
  FilesApp — the reference nOS-native app (Tier F1 + VFS).

  A real file browser over the class-3 per-user tree. It CALLS the BFF VFS API
  (list/read/mkdir/move/delete/upload/download) — it is NOT an iframe. uid is
  pinned server-side; the browser only ever hits same-origin /bff/vfs.

  TOUCH FIRST (operator, 2026-09-23). Two rules follow from that and they are
  why this file does not look like a desktop file manager:
    • no hover-only affordance and no drag-only action. Every action on a row
      is reachable through the row's ⋯ button, which opens an action sheet
      (<Modal>) with 44px targets. Drag-to-move would be the only way to move a
      file on a desktop; here "Move…" opens the file-picker in folder mode.
    • the camera is a native input (`capture="environment"`), not a library.
      On a phone it opens the camera; on a desktop it degrades to a file dialog,
      which is why the button is labelled "Photo" and not "Take photo".

  "Send to accounting" is a MOVE and nothing else: the intake sweep
  (tools/invoice-vision-intake.py) globs `inbox/accounting/*/incoming`, so
  putting the file there IS the hand-off. The per-client leaf is created by
  client onboarding — when none exists we say so rather than minting a guess.

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
		vfsMove,
		vfsDelete,
		vfsUpload,
		vfsDownloadUrl,
		type VfsEntry
	} from '$lib/api/vfs';
	import { crumbs, joinPath, parentPath, basename } from './paths';
	import { openFilePicker } from './file-picker/service';
	import {
		sortEntries,
		uniqueName,
		cameraName,
		queueDest,
		formatSize,
		ACCOUNTING_ROOT,
		type SortKey
	} from './files-ops';
	import { Modal, StatusNote } from '$lib/components/ui';
	import DocViewer from '$lib/components/DocViewer.svelte';
	import { docKind } from '$lib/api/docview';

	let cwd = $state('documents');
	let entries = $state<VfsEntry[]>([]);
	let sortKey = $state<SortKey>('name');
	let loading = $state(false);
	let err = $state('');
	let selected = $state<VfsEntry | null>(null);
	let preview = $state<string | null>(null);
	let previewErr = $state('');
	let busy = $state(false);

	/** The row whose action sheet is open (null = closed). */
	let sheet = $state<VfsEntry | null>(null);
	/** The file waiting for a client pick before it goes to the queue. */
	let queueFor = $state<VfsEntry | null>(null);
	let clients = $state<string[]>([]);

	const shown = $derived(sortEntries(entries, sortKey));

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

	/** Run a VFS mutation, surface its error, and refresh the listing once. */
	async function act(what: string, fn: () => Promise<unknown>) {
		busy = true;
		err = '';
		try {
			await fn();
			await load(cwd);
		} catch (e) {
			err = `${what}: ${e instanceof Error ? e.message : 'failed'}`;
		} finally {
			busy = false;
		}
	}

	async function openEntry(entry: VfsEntry) {
		if (entry.kind === 'dir') {
			void load(joinPath(cwd, entry.name));
			return;
		}
		selected = entry;
		preview = null;
		previewErr = '';
		// Anything DocViewer renders natively (image, PDF) must NOT be read as
		// text first — /read answers 415 on binary and the pane would show that
		// error under a perfectly good preview.
		if (docKind(entry.name) !== 'other') return;
		try {
			preview = await vfsRead(joinPath(cwd, entry.name));
		} catch (e) {
			// Binary / too-large → offer download instead of an inline preview.
			previewErr = e instanceof Error ? e.message : 'cannot preview this file';
		}
	}

	function newFolder() {
		const name = prompt('New folder name');
		if (!name) return;
		void act('mkdir', () => vfsMkdir(joinPath(cwd, name)));
	}

	function rename(entry: VfsEntry) {
		sheet = null;
		const name = prompt(`Rename "${entry.name}" to`, entry.name);
		if (!name || name === entry.name) return;
		if (entries.some((x) => x.name === name)) {
			err = `rename: "${name}" already exists in this folder`; // /move would replace it
			return;
		}
		void act('rename', () => vfsMove(joinPath(cwd, entry.name), joinPath(cwd, name)));
	}

	async function moveTo(entry: VfsEntry) {
		sheet = null;
		const pick = await openFilePicker({
			title: `Move "${entry.name}" to…`,
			startPath: parentPath(cwd),
			allowUpload: false,
			allowDirectories: true
		});
		if (!pick.ok || pick.path === undefined) return;
		const to = pick.path;
		if (joinPath(to, entry.name) === joinPath(cwd, entry.name)) return;
		await act('move', async () => {
			// Same no-overwrite rule as the accounting queue: Bone's /move replaces
			// the destination, so rename around a clash rather than losing a file.
			const there = await vfsList(to);
			const name = uniqueName(
				entry.name,
				there.map((f) => f.name)
			);
			await vfsMove(joinPath(cwd, entry.name), joinPath(to, name));
		});
	}

	function remove(entry: VfsEntry) {
		sheet = null;
		const what =
			entry.kind === 'dir'
				? `Delete the folder "${entry.name}" and everything inside it?`
				: `Delete the file "${entry.name}" (${formatSize(entry.size)})?`;
		if (!confirm(`${what}\n\nThis cannot be undone.`)) return;
		void act('delete', () => vfsDelete(joinPath(cwd, entry.name)));
	}

	// ── Accounting queue ────────────────────────────────────────────────────
	// A move into inbox/accounting/<client>/incoming/. The client leaf is NOT
	// created here (see the header) — an empty list is reported as such.
	async function askQueue(entry: VfsEntry) {
		sheet = null;
		queueFor = entry;
		clients = [];
		err = '';
		try {
			const listing = await vfsList(ACCOUNTING_ROOT);
			clients = listing.filter((c) => c.kind === 'dir').map((c) => c.name);
		} catch (e) {
			err = `accounting inbox: ${e instanceof Error ? e.message : 'unreadable'}`;
			queueFor = null;
		}
	}

	async function sendToQueue(client: string) {
		const entry = queueFor;
		queueFor = null;
		if (!entry) return;
		await act('send to accounting', async () => {
			// Bone's /move REPLACES an existing destination (shutil.move). Two
			// invoices photographed as the same name would silently become one, so
			// rename around a clash instead. vfsList tolerates a missing dir.
			const inbox = await vfsList(`${ACCOUNTING_ROOT}/${client}/incoming`);
			const name = uniqueName(
				entry.name,
				inbox.map((f) => f.name)
			);
			await vfsMove(joinPath(cwd, entry.name), queueDest(client, name));
		});
	}

	// ── Uploads (device picker + camera) ────────────────────────────────────
	async function putFiles(files: File[], nameFor: (f: File, taken: string[]) => string) {
		if (files.length === 0) return;
		busy = true;
		err = '';
		const failed: string[] = [];
		// Track names as we go so two shots in one batch cannot collide.
		const taken = entries.map((e) => e.name);
		try {
			// Sequential — one file at a time keeps memory + the Bone stream sane.
			for (const file of files) {
				const name = nameFor(file, taken);
				taken.push(name);
				try {
					await vfsUpload(cwd, file, name);
				} catch (ex) {
					failed.push(`${file.name}: ${ex instanceof Error ? ex.message : 'upload failed'}`);
				}
			}
			if (failed.length) err = failed.join('; ');
			await load(cwd); // refresh ONCE after all uploads settle
		} finally {
			busy = false;
		}
	}

	async function onUpload(e: Event) {
		const input = e.currentTarget as HTMLInputElement;
		const files = Array.from(input.files ?? []);
		input.value = '';
		// An upload onto an existing name OVERWRITES it in Bone (`open("wb")`),
		// so ask per clashing file rather than losing one silently.
		const here = new Set(entries.map((x) => x.name));
		const go = files.filter(
			(f) => !here.has(f.name) || confirm(`"${f.name}" already exists here. Overwrite it?`)
		);
		await putFiles(go, (f) => f.name);
	}

	async function onCapture(e: Event) {
		const input = e.currentTarget as HTMLInputElement;
		const files = Array.from(input.files ?? []);
		input.value = '';
		// A camera hands over `image.jpg` every time — date-stamp it and never
		// overwrite, so a second shot is a second document.
		await putFiles(files, (f, taken) => uniqueName(cameraName(new Date(), f.name), taken));
	}
</script>

<div class="files">
	<header class="bar">
		<button class="btn" onclick={() => load(cwd)} disabled={busy}>Refresh</button>
		<button class="btn" onclick={newFolder} disabled={busy}>New folder</button>
		<label class="btn upload">
			Upload
			<input type="file" multiple onchange={onUpload} disabled={busy} hidden />
		</label>
		<label class="btn upload">
			📷 Photo
			<input
				type="file"
				accept="image/*"
				capture="environment"
				onchange={onCapture}
				disabled={busy}
				hidden
			/>
		</label>
		<span class="spacer"></span>
		<label class="sort">
			Sort
			<select bind:value={sortKey} aria-label="Sort by">
				<option value="name">name</option>
				<option value="size">size</option>
				<option value="mtime">newest</option>
			</select>
		</label>
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
				<li><StatusNote kind="loading" block={false}>loading…</StatusNote></li>
			{:else if shown.length === 0}
				<li><StatusNote kind="empty" block={false}>empty folder</StatusNote></li>
			{/if}
			{#each shown as entry (entry.path)}
				<li class="row">
					<button
						class="entry"
						class:sel={selected?.path === entry.path}
						onclick={() => openEntry(entry)}
					>
						<span class="ico">{entry.kind === 'dir' ? '📁' : '📄'}</span>
						<span class="name">{entry.name}</span>
						{#if entry.kind === 'file'}<span class="size">{formatSize(entry.size)}</span>{/if}
					</button>
					<button
						class="more"
						aria-label="Actions for {entry.name}"
						disabled={busy}
						onclick={() => (sheet = entry)}>⋯</button
					>
				</li>
			{/each}
		</ul>

		<aside class="pane">
			{#if selected}
				<h4>{selected.name}</h4>
				<p class="meta muted">{formatSize(selected.size)} · {selected.kind}</p>
				<a class="btn dl" href={vfsDownloadUrl(joinPath(cwd, selected.name))} download>Download</a>
				{#if docKind(selected.name) !== 'other'}
					<div class="shot">
						<DocViewer path={joinPath(cwd, selected.name)} alt={selected.name} />
					</div>
				{:else if preview !== null}
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

{#if sheet}
	{@const entry = sheet}
	<Modal title={entry.name} onclose={() => (sheet = null)}>
		<div class="sheet">
			<button
				class="act"
				onclick={() => {
					sheet = null;
					void openEntry(entry);
				}}>{entry.kind === 'dir' ? 'Open folder' : 'Preview'}</button
			>
			{#if entry.kind === 'file'}
				<a class="act" href={vfsDownloadUrl(joinPath(cwd, entry.name))} download>Download</a>
				<button class="act" onclick={() => askQueue(entry)}>Send to accounting queue…</button>
			{/if}
			<button class="act" onclick={() => rename(entry)}>Rename…</button>
			<button class="act" onclick={() => moveTo(entry)}>Move to…</button>
			<button class="act danger" onclick={() => remove(entry)}>Delete…</button>
		</div>
	</Modal>
{/if}

{#if queueFor}
	{@const entry = queueFor}
	<Modal title="Send to accounting" onclose={() => (queueFor = null)}>
		{#if clients.length === 0}
			<StatusNote kind="empty" title="No client inbox yet">
				Nothing under <code>{ACCOUNTING_ROOT}/</code>. A client folder is created when that client
				is onboarded — this browser will not invent one.
			</StatusNote>
		{:else}
			<p class="muted">
				Moves <strong>{entry.name}</strong> out of
				<code>{basename(cwd) || 'home'}</code> into the client's
				<code>incoming/</code> folder, where the accounting sweep picks it up.
			</p>
			<div class="sheet">
				{#each clients as client (client)}
					<button class="act" onclick={() => sendToQueue(client)}>{client}</button>
				{/each}
			</div>
		{/if}
	</Modal>
{/if}

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
		align-items: center;
	}
	.spacer {
		flex: 1;
	}
	.btn {
		background: rgba(255, 255, 255, 0.08);
		color: var(--fg);
		border: none;
		padding: 8px 14px;
		min-height: 40px;
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
	.sort {
		color: var(--muted);
		font-size: 12px;
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.sort select {
		background: rgba(255, 255, 255, 0.08);
		color: var(--fg);
		border: none;
		border-radius: 8px;
		padding: 7px 8px;
		font-size: 12px;
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
		padding: 6px 6px;
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
	.row {
		display: flex;
		align-items: center;
		gap: 2px;
	}
	.entry {
		flex: 1;
		min-width: 0;
		display: flex;
		align-items: center;
		gap: 10px;
		background: none;
		border: none;
		color: var(--fg);
		padding: 10px 8px;
		min-height: 44px;
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
	.more {
		flex: 0 0 auto;
		width: 44px;
		height: 44px;
		background: none;
		border: none;
		border-radius: 8px;
		color: var(--muted);
		font-size: 16px;
		cursor: pointer;
	}
	.more:hover {
		background: rgba(255, 255, 255, 0.06);
		color: var(--fg);
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
	.shot {
		max-width: 100%;
		border-radius: 8px;
		align-self: flex-start;
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
	.sheet {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.act {
		display: block;
		width: 100%;
		min-height: 44px;
		padding: 10px 12px;
		border: none;
		border-radius: 8px;
		background: rgba(255, 255, 255, 0.08);
		color: var(--fg);
		font-size: 13px;
		text-align: left;
		text-decoration: none;
		cursor: pointer;
		box-sizing: border-box;
	}
	.act:hover {
		background: rgba(255, 255, 255, 0.14);
	}
	.act.danger {
		color: #ff8080;
	}
	.muted {
		color: var(--muted);
	}
	.err {
		color: #ff8080;
		font-size: 12px;
		margin: 0;
	}
	/* Touch/narrow: the preview stacks under the list instead of stealing 44%. */
	@media (max-width: 640px) {
		.split {
			flex-direction: column;
		}
		.pane {
			width: auto;
			border-left: none;
			border-top: 1px solid var(--glass-brd);
			padding-left: 0;
			padding-top: 10px;
		}
	}
</style>
