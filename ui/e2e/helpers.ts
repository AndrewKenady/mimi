import { expect, type Page } from '@playwright/test';

/** Sign in as the owner (the fixture isn't on the device's loopback port) and land on `to`. */
export async function signIn(page: Page, to = '/') {
	await page.goto(`/__fixture/login?to=${encodeURIComponent(to)}`);
	await waitForApp(page);
}

/** The app removes its boot splash once it has loaded and mounted its shell (and its keyboard
 *  shortcuts); acting before that races the app on slower machines such as CI runners. */
export async function waitForApp(page: Page) {
	await page.waitForFunction(() => !document.getElementById('boot'), null, { timeout: 15_000 });
}

/** Switch the scripted model: grounded | ungrounded | error | chitchat. */
export async function mode(page: Page, m: 'grounded' | 'ungrounded' | 'error' | 'chitchat') {
	const r = await page.request.post(`/__fixture/mode/${m}`);
	expect(r.ok()).toBeTruthy();
}

export async function setTheme(page: Page, theme: 'dark' | 'light') {
	const r = await page.request.patch('/api/settings/user/appearance', { data: { theme } });
	expect(r.ok()).toBeTruthy();
}

/** Fail the test on uncaught page errors and console errors, which users would never see. */
export function watchErrors(page: Page): string[] {
	const errors: string[] = [];
	page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
	page.on('console', (m) => {
		if (m.type() === 'error' && !/favicon|Failed to load resource/.test(m.text())) errors.push(`console: ${m.text()}`);
	});
	return errors;
}

export async function ask(page: Page, question: string) {
	const box = page.getByRole('textbox', { name: 'Message' }).first();
	await box.fill(question);
	await box.press('Enter');
}
