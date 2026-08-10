/**
 * The Bone projection's job is to keep three things apart that all look like
 * "fine" from a distance: the daemon answering, the vein carrying, and the
 * surfaces this view is not allowed to see.
 */
import { describe, it, expect } from 'vitest';
import { projectBone, humanUptime, SCOPE_GATED } from './bone';

const OK_VFS = { ok: true, detail: 'stat / succeeded with the face VFS bearer' };

describe('liveness is not health', () => {
	it('reports alive from a real /api/health body', () => {
		// Field names copied from a live response.
		const b = projectBone({ status: 'ok', uptime: 138309, auth_ready: true }, OK_VFS);
		expect(b.alive).toBe(true);
		expect(b.uptimeSeconds).toBe(138309);
		expect(b.authReady).toBe(true);
	});

	it('keeps `status: ok` and `auth_ready: false` both visible', () => {
		// The combination that matters: Bone answers liveness while every
		// scope-gated endpoint returns 503. Collapsing the two into one green
		// light is the ten-days-healthy defect in miniature.
		const b = projectBone({ status: 'ok', uptime: 10, auth_ready: false }, OK_VFS);
		expect(b.alive).toBe(true);
		expect(b.status).toBe('ok');
		expect(b.authReady).toBe(false);
	});

	it('is not alive when the probe itself failed', () => {
		const b = projectBone({}, OK_VFS, 'connection refused');
		expect(b.alive).toBe(false);
		expect(b.error).toBe('connection refused');
	});

	it('leaves auth_ready null when the field is absent, never false', () => {
		// Absent and false are different: one is "Bone did not say", the other
		// is "Bone said no".
		expect(projectBone({ status: 'ok' }, OK_VFS).authReady).toBeNull();
	});
});

describe('the vein is probed separately from the organ', () => {
	it('records a failing VFS beside a healthy daemon', () => {
		const b = projectBone(
			{ status: 'ok', uptime: 1, auth_ready: true },
			{
				ok: false,
				detail: '401 Authorization: Bearer <token> required'
			}
		);
		expect(b.alive).toBe(true);
		expect(b.vfs.ok).toBe(false);
		expect(b.vfs.detail).toContain('401');
	});
});

describe('the gaps are data', () => {
	it('always declares what this view cannot read', () => {
		// Not an empty panel. A surface that shows nothing where it cannot look
		// teaches the operator there is nothing there.
		const b = projectBone({ status: 'ok' }, OK_VFS);
		expect(b.gaps.length).toBeGreaterThan(0);
		expect(b.gaps).toEqual(SCOPE_GATED);
	});

	it('gives every gap a reason, not just a name', () => {
		for (const g of SCOPE_GATED) {
			expect(g.endpoint, 'gap without an endpoint').toBeTruthy();
			expect(g.reason.length, `${g.endpoint} has no reason`).toBeGreaterThan(20);
		}
	});
});

describe('humanUptime', () => {
	it('formats the ranges', () => {
		expect(humanUptime(30)).toBe('30s');
		expect(humanUptime(600)).toBe('10m');
		expect(humanUptime(3700)).toBe('1h 1m');
		expect(humanUptime(138309)).toBe('1d 14h');
	});

	it('says unknown rather than guessing zero', () => {
		expect(humanUptime(null)).toBe('unknown');
		expect(humanUptime(-1)).toBe('unknown');
	});
});
