/** File-picker-as-a-service — public contract. */

export interface FilePickerOptions {
	/** Dialog heading. */
	title?: string;
	/** Starting VFS dir for the "from nOS" browse mode. Default `documents`. */
	startPath?: string;
	/** Offer the "from device" (upload-into-VFS) mode. Default `true`. */
	allowUpload?: boolean;
	/** VFS dir uploads land in (from-device mode). Default `inbox`. */
	uploadDir?: string;
	/** Allow picking a directory (else only files are selectable). Default `false`. */
	allowDirectories?: boolean;
}

export interface PickResult {
	/** `false` when the user cancelled/closed the dialog. */
	ok: boolean;
	/** How the file was chosen. */
	mode?: 'nos' | 'device';
	/** The VFS-relative path of the picked/uploaded file (or dir). */
	path?: string;
	/** The final path segment (display name). */
	name?: string;
	/** `'dir' | 'file'` of the pick. */
	kind?: 'dir' | 'file';
}

/** The cancelled result — a stable object callers can compare against. */
export const CANCELLED: PickResult = { ok: false };
