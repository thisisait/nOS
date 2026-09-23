import { describe, it, expect } from 'vitest';
import { docKind, nextcloudFolderUrl, NOS_FILES_MOUNT } from './docview';

describe('docKind', () => {
	it('recognizes pdf and common image extensions', () => {
		expect(docKind('a/b/invoice.pdf')).toBe('pdf');
		expect(docKind('scan.JPG')).toBe('image');
		expect(docKind('photo.png')).toBe('image');
	});

	it('falls back to other for anything else, including no extension', () => {
		expect(docKind('report.docx')).toBe('other');
		expect(docKind('README')).toBe('other');
		expect(docKind('')).toBe('other');
	});
});

describe('nextcloudFolderUrl', () => {
	it('points at the nOS files mount plus the containing folder', () => {
		const url = nextcloudFolderUrl('https://cloud.dev.local', 'documents/acme/invoice.docx');
		expect(url).toBe(
			`https://cloud.dev.local/index.php/apps/files/?dir=${encodeURIComponent(
				`/${NOS_FILES_MOUNT}/documents/acme`
			)}`
		);
	});

	it('roots at the mount itself when the path has no folder', () => {
		const url = nextcloudFolderUrl('https://cloud.dev.local', 'report.docx');
		expect(url).toBe(
			`https://cloud.dev.local/index.php/apps/files/?dir=${encodeURIComponent(`/${NOS_FILES_MOUNT}`)}`
		);
	});

	it('strips a trailing slash on the base url', () => {
		expect(nextcloudFolderUrl('https://cloud.dev.local/', 'x.docx')).toContain(
			'https://cloud.dev.local/index.php'
		);
	});

	it('returns empty when Nextcloud has no known base url', () => {
		expect(nextcloudFolderUrl('', 'x.docx')).toBe('');
	});

	it('knows the formats a phone camera produces', () => {
		expect(docKind('photo-20260923-143005.heic')).toBe('image');
		expect(docKind('shot.avif')).toBe('image');
	});
});
