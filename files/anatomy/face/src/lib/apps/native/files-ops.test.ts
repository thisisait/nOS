import { describe, it, expect } from 'vitest';
import {
	sortEntries,
	uniqueName,
	cameraName,
	queueDest,
	formatSize,
	ACCOUNTING_ROOT
} from './files-ops';
import type { VfsEntry } from '$lib/api/vfs';

const e = (name: string, kind: 'dir' | 'file', size = 0, mtime = 0): VfsEntry => ({
	name,
	path: name,
	kind,
	size,
	mtime
});

describe('sortEntries', () => {
	const listing = [
		e('zeta.txt', 'file', 10, 300),
		e('beta', 'dir', 0, 100),
		e('alpha.txt', 'file', 900, 200),
		e('omega', 'dir', 0, 400)
	];

	it('always puts directories first, whatever the key', () => {
		for (const key of ['name', 'size', 'mtime'] as const) {
			const kinds = sortEntries(listing, key).map((x) => x.kind);
			expect(kinds).toEqual(['dir', 'dir', 'file', 'file']);
		}
	});

	it('sorts by name, size (largest first) and mtime (newest first)', () => {
		expect(sortEntries(listing, 'name').map((x) => x.name)).toEqual([
			'beta',
			'omega',
			'alpha.txt',
			'zeta.txt'
		]);
		expect(
			sortEntries(listing, 'size')
				.map((x) => x.name)
				.slice(2)
		).toEqual(['alpha.txt', 'zeta.txt']);
		expect(
			sortEntries(listing, 'mtime')
				.map((x) => x.name)
				.slice(2)
		).toEqual(['zeta.txt', 'alpha.txt']);
	});

	it('does not mutate the input', () => {
		const copy = [...listing];
		sortEntries(listing, 'size');
		expect(listing).toEqual(copy);
	});
});

describe('uniqueName', () => {
	it('returns the name untouched when free', () => {
		expect(uniqueName('a.jpg', ['b.jpg'])).toBe('a.jpg');
	});

	it('suffixes before the extension, skipping every taken candidate', () => {
		expect(uniqueName('a.jpg', ['a.jpg'])).toBe('a-2.jpg');
		expect(uniqueName('a.jpg', ['a.jpg', 'a-2.jpg', 'a-3.jpg'])).toBe('a-4.jpg');
	});

	it('handles extensionless names and dotfiles', () => {
		expect(uniqueName('notes', ['notes'])).toBe('notes-2');
		expect(uniqueName('.env', ['.env'])).toBe('.env-2'); // leading dot is not an extension
	});
});

describe('cameraName', () => {
	const t = new Date(2026, 8, 23, 14, 30, 5); // 2026-09-23 14:30:05 local

	it('stamps the capture time and keeps the extension', () => {
		expect(cameraName(t, 'image.jpg')).toBe('photo-20260923-143005.jpg');
		expect(cameraName(t, 'IMG_0001.PNG')).toBe('photo-20260923-143005.png');
	});

	it('defaults to .jpg when the phone gives no filename', () => {
		expect(cameraName(t)).toBe('photo-20260923-143005.jpg');
	});
});

describe('queueDest', () => {
	it('is exactly the dir the accounting sweep globs', () => {
		// tools/invoice-vision-intake.py::discover_intakes →
		//   tenants/*/users/*/inbox/accounting/*/incoming
		expect(queueDest('acme', 'photo-1.jpg')).toBe('inbox/accounting/acme/incoming/photo-1.jpg');
		expect(queueDest('acme', 'x').startsWith(`${ACCOUNTING_ROOT}/`)).toBe(true);
	});
});

describe('formatSize', () => {
	it('reads as bytes below 1 kB and scales above it', () => {
		expect(formatSize(0)).toBe('0 B');
		expect(formatSize(1023)).toBe('1023 B');
		expect(formatSize(1536)).toBe('1.5 kB');
		expect(formatSize(5 * 1024 * 1024)).toBe('5.0 MB');
	});
});
