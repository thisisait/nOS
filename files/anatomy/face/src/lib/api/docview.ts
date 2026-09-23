/**
 * Shared "how do I show this document" logic for BooksApp + FilesApp.
 *
 * The browser can render exactly two kinds of document natively: images and
 * PDF (both already proven inline in BooksApp's verify queue). Everything
 * else — office formats a tenant's documents/ tree actually holds (docx,
 * xlsx, odt, …) — has no browser-native renderer, and this estate does not
 * add one: the honest floor is a deep link into Nextcloud, which already
 * mounts the SAME per-user tree as external storage named "nOS files"
 * (roles/pazny.nextcloud/tasks/post.yml, datadir=/nos-user-files/$user ==
 * Bone's _user_root — roles/pazny.nextcloud/templates/compose.yml.j2:29) and
 * already registers OnlyOffice as the default editor for office formats
 * (defFormats/editFormats, same post.yml). Opening the containing folder
 * (not a `?openfile=` deep link) is the reachable floor — a per-file id
 * needs a WebDAV PROPFIND round-trip this estate does not otherwise make,
 * see the DocViewer.svelte header for the fuller account.
 *
 * Pure module — no Svelte import — so vitest runs it in node.
 */

// heic/avif are here because a phone camera produces them and the Files
// explorer's capture path hands them straight to this viewer.
const IMAGE_EXTS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg', 'heic', 'avif']);

export type DocKind = 'image' | 'pdf' | 'other';

/** Extension-sniffed kind of a VFS-relative path (no content-type probe —
 *  the extension is also all BooksApp's `sourceKind` ever had). */
export function docKind(path: string): DocKind {
	const ext = (path.split('.').pop() ?? '').toLowerCase();
	if (ext === 'pdf') return 'pdf';
	if (IMAGE_EXTS.has(ext)) return 'image';
	return 'other';
}

/** The mount name post.yml registers the class-3 tree under in Nextcloud —
 *  the one string both sides must agree on. */
export const NOS_FILES_MOUNT = 'nOS files';

/** A same-session Nextcloud Files-app URL for the FOLDER containing `path`
 *  (VFS-relative, e.g. "documents/acme/invoice.pdf"). `nextcloudBaseUrl` is
 *  the hub catalog's plain origin (e.g. "https://cloud.dev.local") — pass ''
 *  when Nextcloud isn't installed/enabled and the caller gets '' back (no
 *  dead link rendered). */
export function nextcloudFolderUrl(nextcloudBaseUrl: string, path: string): string {
	if (!nextcloudBaseUrl) return '';
	const slash = path.lastIndexOf('/');
	const folder = slash === -1 ? '' : path.slice(0, slash);
	const dir = `/${NOS_FILES_MOUNT}${folder ? '/' + folder : ''}`;
	return `${nextcloudBaseUrl.replace(/\/+$/, '')}/index.php/apps/files/?dir=${encodeURIComponent(dir)}`;
}
