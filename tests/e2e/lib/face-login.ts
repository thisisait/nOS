/**
 * tests/e2e/lib/face-login.ts — one Authentik login in a real browser, saved as storageState.
 *
 * The face sits behind forward_auth: every face/Iris journey needs a signed-in context. globalSetup
 * logs the run's tester in once (FACE_E2E=1) and playwright.config.ts hands the saved state to
 * every test, so a journey starts on the desktop, not on the login form.
 */
import { chromium, expect } from '@playwright/test';

export async function faceLogin(faceUrl: string, username: string, password: string, statePath: string): Promise<void> {
	const browser = await chromium.launch();
	try {
		const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
		const page = await ctx.newPage();
		const onAuth = () => new URL(page.url()).hostname.startsWith('auth.');
		try {
			await page.goto(faceUrl);
			if (onAuth()) {
				const uid = page.locator('input[name="uidField"]:visible');
				await uid.fill(username, { timeout: 20_000 });
				await page.locator('button[type="submit"]:visible').click();
				// The password stage renders after the identification stage answers ("Not you?" beside the
				// name); filling before that lands in a field the re-render clears.
				await page.getByText('Not you?').waitFor({ timeout: 20_000 });
				const pw = page.getByPlaceholder('Please enter your password');
				await pw.fill(password);
				await expect(pw).not.toHaveValue('');
				await pw.press('Enter');
				await page.waitForURL((u) => !u.hostname.startsWith('auth.'), { timeout: 30_000 });
			}
			await page.waitForLoadState('networkidle');
			if (onAuth()) throw new Error('still on Authentik after login');
			await ctx.storageState({ path: statePath });
		} catch (e) {
			// What the login form said is the evidence: keep it beside the state file.
			await page.screenshot({ path: statePath.replace(/\.json$/, '.failed.png'), fullPage: true }).catch(() => {});
			throw new Error(`face login failed at ${page.url()}: ${e}`);
		}
	} finally {
		await browser.close();
	}
}
