/**
 * tests/e2e/journeys/face-v0.2.spec.ts
 *
 * JOURNEY STUBS — nOS-face v0.2 acceptance flows (Wave-2 G7).
 *
 * `describe.skip`-ped by default: they need a running face shell behind Authentik
 * (the SvelteKit BFF on FACE_URL) plus a live Bone (VFS + user-state) and,
 * optionally, KEAP. Un-skip (or gate on FACE_E2E=1) once a face fixture is wired
 * into global-setup with an authenticated context. Companion: face-snap.spec.ts.
 *
 * These pin the v0.2 headline features end-to-end (docs/plans/nos-face-shell-v2.md):
 *   A. Wallpaper — open Control Panel → Wallpaper; add a gradient row; it appears
 *      in the picker; selecting it changes the desktop background AND persists
 *      (reload → still applied) via Bone user-state ns `face.desktop`.
 *   B. Per-viewport window restore — open + move windows; wait for the 30 s
 *      debounced write to `face.windows["<w>x<h>"]`; reload at the SAME viewport →
 *      window geometry is restored; at a DIFFERENT viewport → cascade (unaffected).
 *   C. Control Panel opens a WINDOW (not a modal) — click a control row; a Window
 *      with the surface (rawDataTable / editor) appears in the window layer.
 *   D. Native app calls an API (no iframe) — launch the Files native app; it lists
 *      a real folder via /bff/vfs (a fetch to the BFF, not an <iframe> src).
 */

import { test, expect, type Page } from '@playwright/test';

const FACE_URL = process.env.FACE_URL ?? `https://os.${process.env.NOS_HOST ?? 'dev.local'}/`;

test.describe.skip('nOS-face v0.2 acceptance', () => {
	test('A · a user-added wallpaper applies and persists', async ({ page }: { page: Page }) => {
		await page.goto(FACE_URL);
		await page.getByRole('button', { name: 'Control Panel' }).click();
		// Open the Wallpaper surface, add a gradient row, select it.
		await page.getByText('Wallpaper').click();
		// … add-row UI (rawDataTable) → new gradient row …
		// Assert the desktop background changed and survives a reload.
		await page.reload();
		const bg = await page.locator('.desktop').evaluate((el) => getComputedStyle(el).backgroundImage);
		expect(bg).not.toBe('none');
	});

	test('B · window positions restore per viewport bucket', async ({ page }: { page: Page }) => {
		await page.setViewportSize({ width: 1440, height: 900 });
		await page.goto(FACE_URL);
		// launch an app, move its window to a known spot, wait for the debounced write
		// (test harness may stub the 30 s timer), reload at the same viewport.
		await page.reload();
		// Assert the window is where it was left (restored from face.windows["1400x900"]).
		expect(true).toBeTruthy(); // placeholder assertion until the fixture lands
	});

	test('C · a control-panel row opens a window, not a modal', async ({ page }: { page: Page }) => {
		await page.goto(FACE_URL);
		await page.getByRole('button', { name: 'Control Panel' }).click();
		// A control-panel window must be a real Window (role=dialog in the window layer),
		// not an overlay modal.
		await expect(page.locator('.win')).toHaveCount(1);
	});

	test('D · a native app calls the API (no iframe)', async ({ page }: { page: Page }) => {
		await page.goto(FACE_URL);
		// The Files native app is a component that fetches /bff/vfs — assert a real
		// request is made and NO <iframe> is used for it.
		const [req] = await Promise.all([
			page.waitForRequest((r) => r.url().includes('/bff/vfs')),
			page.getByRole('button', { name: /Files/ }).click()
		]);
		expect(req.url()).toContain('/bff/vfs');
		await expect(page.locator('.win iframe')).toHaveCount(0);
	});
});
