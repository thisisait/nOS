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

	// App limbs (writes:false, no card): tables.open_table runs in the face and the person sees it.
	// The model may answer without acting; the journey then fails on the missing window.
	test('"open my roadmap table" brings Tables forward with roadmap selected', async ({ page }: { page: Page }) => {
		await page.goto(FACE_URL);
		await page.getByRole('button', { name: 'Iris' }).first().click();
		const box = page.getByRole('dialog', { name: 'Iris' }).locator('textarea').first();
		await expect(box).toBeEnabled({ timeout: 20_000 });
		await box.fill('Open my roadmap table.');
		await box.press('Enter');
		const tables = page.getByRole('dialog', { name: 'Tables' });
		await expect(tables).toBeVisible({ timeout: 60_000 });
		await expect(tables.locator('.t.sel')).toContainText(/roadmap/i, { timeout: 20_000 });
	});

	// The first write limb (files.move, writes:true): a card first, the move only on Approve, then
	// Files shows the file in its new folder. Uploads its own report.pdf, moves it back after.
	test('"move report.pdf to archive" asks, and on approve Files shows it in archive', async ({ page }: { page: Page }) => {
		await page.goto(FACE_URL);
		const vfs = (op: string, body: object) =>
			page.evaluate(async ([op, body]) => {
				const r = await fetch('/bff/vfs', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ op, ...body }) });
				return r.status;
			}, [op, body] as const);
		expect(await vfs('mkdir', { path: 'documents/archive' })).toBeLessThan(300);
		expect(await vfs('write', { path: 'documents/report.pdf', content: 'e2e residue probe' })).toBeLessThan(300);
		try {
			await page.getByRole('button', { name: 'Iris' }).first().click();
			const iris = page.getByRole('dialog', { name: 'Iris' });
			const box = iris.locator('textarea').first();
			await expect(box).toBeEnabled({ timeout: 20_000 });
			await box.fill('Move documents/report.pdf to documents/archive.');
			await box.press('Enter');
			const card = iris.locator('[data-approval]');
			await expect(card).toContainText('documents/archive', { timeout: 60_000 });
			await card.getByRole('button', { name: 'approve' }).click();
			const files = page.getByRole('dialog', { name: 'Files' });
			await expect(files.locator('.crumbs')).toContainText('archive', { timeout: 20_000 });
			await expect(files.locator('.entry.sel')).toContainText('report.pdf');
		} finally {
			await vfs('move', { src: 'documents/archive/report.pdf', dst: 'documents/report.pdf' });
			await vfs('delete', { path: 'documents/report.pdf' });
		}
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
