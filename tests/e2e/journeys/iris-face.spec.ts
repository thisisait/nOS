/**
 * tests/e2e/journeys/iris-face.spec.ts — Iris in the face, over the optic nerve (iris-face-app).
 *
 * Gated on FACE_E2E=1 (pattern face-v0.2.spec.ts): needs the face behind Authentik with an
 * authenticated context, a thalamus serving its relay door, and the person in the identity map.
 * Open Iris, send a turn, see the answer; the stream is one SSE response from bff/iris/stream.
 * Not yet run live. The ledger half (session actor user:<uid>, peer.via face) is a reader's.
 */
import { test, expect, type Page } from '@playwright/test';

const FACE_URL = process.env.FACE_URL ?? `https://os.${process.env.NOS_HOST ?? 'dev.local'}/`;

test.describe('Iris in the face', () => {
	test.skip(process.env.FACE_E2E !== '1', 'FACE_E2E=1 needs a live face + thalamus relay');

	test('a turn goes over the optic nerve and its answer renders', async ({ page }: { page: Page }) => {
		const stream = page.waitForResponse((r) => r.url().includes('/bff/iris/stream'));
		await page.goto(FACE_URL);
		await page.getByRole('button', { name: 'Iris' }).first().click();
		const res = await stream;
		expect(res.status()).toBe(200);
		expect(res.headers()['content-type']).toContain('text/event-stream');

		const box = page.locator('.win textarea').first();
		await expect(box).toBeEnabled({ timeout: 20_000 });
		const sent = page.waitForResponse((r) => r.url().includes('/bff/iris/send') && r.request().method() === 'POST');
		await box.fill('What is on the roadmap?');
		await box.press('Enter');
		expect((await sent).status()).toBe(204);
		// One answer from the thalamus lands in the window (a message or a widget).
		await expect(page.locator('.win').getByText('What is on the roadmap?')).toBeVisible();
	});

	// Contract 9 (operator 2026-10-18): a running turn stops, /branch makes a tab, /clear empties the chat.
	test('a turn stops on Stop, /branch adds a tab, /clear empties the chat', async ({ page }: { page: Page }) => {
		await page.goto(FACE_URL);
		await page.getByRole('button', { name: 'Iris' }).first().click();
		const win = page.locator('.win');
		const box = win.locator('textarea').first();
		await expect(box).toBeEnabled({ timeout: 20_000 });
		await box.fill('Count the rows of every table, one by one.');
		await box.press('Enter');
		await win.getByRole('button', { name: 'stop' }).click({ timeout: 20_000 });
		await expect(win.getByText('Stopped.')).toBeVisible({ timeout: 10_000 });
		await expect(win.getByRole('button', { name: 'stop' })).toHaveCount(0);

		const tabs = page.getByRole('tab');
		const before = await tabs.count();
		await box.fill('/branch');
		await box.press('Enter');
		await expect(tabs).toHaveCount(before + 1);

		await box.fill('/clear');
		await box.press('Enter');
		await expect(win.getByText('Stopped.')).toHaveCount(0);
	});

	test('a cross-site POST to bff/iris/send is refused', async ({ page }: { page: Page }) => {
		await page.goto(FACE_URL);
		const status = await page.evaluate(async () => {
			const r = await fetch('/bff/iris/send', { method: 'POST', body: '{"t":"resume"}', headers: { 'content-type': 'text/plain' } });
			return r.status;
		});
		expect(status).toBe(403);
	});
});
