/**
 * tests/e2e/journeys/face-snap.spec.ts
 *
 * JOURNEY STUB — nOS-face WM v2 drag → snap → tiling (Wave-1 G3).
 *
 * Documents the intended end-to-end flow for Wave-2 G7 to flesh out. It is
 * `describe.skip`-ped by default: it needs a running face shell (the SvelteKit
 * BFF on FACE_URL, default https://os.<NOS_HOST>/) with at least one catalog app
 * so a window can be opened and dragged. Remove `.skip` (or gate on a
 * `FACE_SNAP_E2E=1` env) once a face fixture is wired into global-setup.
 *
 * The flow under test (see docs/archive/nos-face-shell-v2.md §1):
 *   1. Load the desktop; `initWindowManager()` has registered the SnapEngine and
 *      loaded `face.layouts` (or the built-in fallback set).
 *   2. Launch an app from the dock → a Window appears (WM v1 chrome).
 *   3. Pointer-drag the window titlebar toward the TOP edge of the desktop.
 *   4. A dropzone appears (SnapOverlay); reaching the top trigger band GROWS it
 *      and reveals the active layout's CELLS as highlightable drop targets.
 *   5. Move over a cell → it highlights (`.cell.hot`).
 *   6. Release the pointer → the window snaps into that cell (tiled mode):
 *      geometry matches the cell rect and `snappedCell` is set.
 *
 * Run (once un-skipped):
 *   FACE_URL=https://os.dev.local npx playwright test face-snap.spec.ts
 */

import { test, expect, type Page } from '@playwright/test';

const FACE_URL = process.env.FACE_URL ?? `https://os.${process.env.NOS_HOST ?? 'dev.local'}/`;

/** Drag helper: press on `from`, move through `waypoints`, release at the last. */
async function dragThrough(
	page: Page,
	from: { x: number; y: number },
	waypoints: Array<{ x: number; y: number }>
): Promise<void> {
	await page.mouse.move(from.x, from.y);
	await page.mouse.down();
	for (const p of waypoints) {
		await page.mouse.move(p.x, p.y, { steps: 8 });
	}
	await page.mouse.up();
}

test.describe.skip('nOS-face WM v2 — drag → snap → tiling', () => {
	test('dragging a window to a top-edge cell snaps it into tiled mode', async ({ page }) => {
		await page.goto(FACE_URL, { waitUntil: 'domcontentloaded', timeout: 30_000 });

		// 1. Launch the first dock app → a window opens.
		const firstTile = page.locator('nav.dock button.tile').first();
		await firstTile.click();
		const win = page.locator('section.win').first();
		await expect(win).toBeVisible();

		// 2. Grab the titlebar and drag toward the top edge (through the trigger
		//    band) into the RIGHT half cell of the default half-v layout.
		const bar = win.locator('header.titlebar');
		const box = await bar.boundingBox();
		if (!box) throw new Error('titlebar has no bounding box');
		const grip = { x: box.x + box.width / 2, y: box.y + box.height / 2 };

		const vw = page.viewportSize()?.width ?? 1280;
		await dragThrough(page, grip, [
			{ x: vw * 0.75, y: 40 }, // enter the top trigger band → overlay grows
			{ x: vw * 0.75, y: 300 } // hover the right-half cell, then release
		]);

		// 3. The overlay is gone and the window is snapped to the right half:
		//    left edge ~ half the viewport, width ~ half the viewport.
		await expect(page.locator('.snap-overlay')).toHaveCount(0);
		const snapped = await win.boundingBox();
		if (!snapped) throw new Error('window has no bounding box after snap');
		expect(snapped.x).toBeGreaterThan(vw * 0.4);
		expect(snapped.width).toBeLessThan(vw * 0.6);
	});
});
