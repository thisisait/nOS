<!--
  DocViewer — the one surface for "show me this VFS document", shared by
  BooksApp (invoice verify queue) and FilesApp (file browser preview).

  Inline renders what the browser can render natively: images (<img>) and
  PDF (<object>) — exactly BooksApp's original verify-queue markup, now in
  one place instead of duplicated per caller.

  For everything else (docx/xlsx/odt/… — what a tenant's documents/ tree
  actually holds), there is no browser-native renderer and this estate does
  not add one. The reachable floor: Nextcloud already mounts the SAME
  per-user tree as external storage ("nOS files",
  roles/pazny.nextcloud/tasks/post.yml) and already registers OnlyOffice as
  the default editor for office formats there — so a same-session deep link
  into that Nextcloud folder is a real, working "open this document" action,
  not a dead end. It opens the CONTAINING FOLDER, not the file directly: a
  file-level `?openfile=` link needs the Nextcloud fileid, which needs a
  WebDAV PROPFIND this estate does not otherwise make from the face — the
  operator's own floor ("při nejhorším routování v novém tabu") is satisfied
  by the folder link plus one click, not by that round trip.

  Dolibarr is deliberately NOT wired here: its documents live in Dolibarr's
  own store, under no VFS path the face knows about — there is nothing to
  deep-link FROM. Dolibarr is already a hub app (dolibarr-base's hub_card),
  openable as its own face window/new tab; that is the honest floor for it
  today.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { vfsDownloadUrl } from '$lib/api/vfs';
	import { hubApps } from '$lib/api/hub';
	import { docKind, nextcloudFolderUrl } from '$lib/api/docview';
	import { StatusNote } from './ui';

	let { path, alt = '' }: { path: string; alt?: string } = $props();

	let nextcloudBaseUrl = $state('');
	onMount(async () => {
		try {
			const apps = await hubApps();
			nextcloudBaseUrl = apps.find((a) => a.slug === 'nextcloud')?.url ?? '';
		} catch {
			// Hub catalog down → no deep link; download still works.
		}
	});

	const url = $derived(vfsDownloadUrl(path));
	const kind = $derived(docKind(path));
	const openInNextcloud = $derived(nextcloudFolderUrl(nextcloudBaseUrl, path));
</script>

{#if kind === 'image'}
	<img src={url} alt={alt || path} />
{:else if kind === 'pdf'}
	<object data={url} type="application/pdf" title={alt || path}>
		<a href={url}>Open the original PDF</a>
	</object>
{:else}
	<StatusNote kind="empty">
		No inline preview for this file type. <a href={url} download>Download</a>
		{#if openInNextcloud}
			· <a href={openInNextcloud} target="_blank" rel="noopener">Open folder in Nextcloud ↗</a>
		{/if}
	</StatusNote>
{/if}

<style>
	img,
	object {
		max-width: 100%;
		height: auto;
		min-height: 320px;
		border: 1px solid rgba(128, 128, 128, 0.4);
	}
</style>
