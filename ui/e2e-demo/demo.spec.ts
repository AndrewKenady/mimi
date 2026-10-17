import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';

const DEMO = '/mimi/demo/';
const bar = (page: Page) => page.locator('#mimi-demo-bar');

/** Open a demo URL and wait for the app to mount (it removes its boot splash). */
async function open(page: Page, path = '') {
	await page.goto(DEMO + path);
	await page.waitForFunction(() => !document.getElementById('boot'), null, { timeout: 20_000 });
}

/** Errors a visitor's console would show, minus the 404 status GitHub Pages gives a deep link. */
function watchErrors(page: Page): string[] {
	const errors: string[] = [];
	page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
	page.on('console', (m) => {
		if (m.type() === 'error' && !/Failed to load resource: the server responded with a status of 404/.test(m.text())) errors.push(m.text());
	});
	return errors;
}

test('home loads with the demo banner and no errors', async ({ page }) => {
	const errors = watchErrors(page);
	await open(page);
	await expect(bar(page)).toContainText('Live demo');
	await expect(bar(page)).toContainText('recorded answers');
	await expect(page.getByText(/(Still up|Good (morning|afternoon|evening)), Ada/)).toBeVisible();
	await expect(page.getByText(/Can’t reach|Can't reach|Reconnecting/)).toHaveCount(0);
	expect(errors).toEqual([]);
});

test('the guided question streams sources first, then a cited answer, under the base path', async ({ page }) => {
	await open(page);
	await bar(page).getByRole('switch', { name: 'Skip the wait' }).click();
	await bar(page).locator('button.step').click();
	await expect(page).toHaveURL(/\/mimi\/demo\/chat\//);
	await expect(page.getByText('From the source').first()).toBeVisible();
	const answer = page.locator('.prose.answer').last();
	await expect(answer).toContainText('get help as fast as you can', { timeout: 30_000 });
	await expect(page.getByText('Gemma 4 12B')).toBeVisible();
	await page.locator('.cite[data-cite="1"]').first().click();
	await expect(page).toHaveURL(/\/mimi\/demo\/library\/read\/wikimed\//);
	await expect(page.getByRole('heading', { name: 'Hypothermia', level: 1 })).toBeVisible();
});

test('the flagged answer shows its citation warning', async ({ page }) => {
	await open(page);
	await bar(page).getByRole('switch', { name: 'Skip the wait' }).click();
	await bar(page).getByRole('button', { name: 'Can a hot bath treat hypothermia?' }).click();
	await expect(page.locator('details.checkcite')).toContainText("couldn't be matched", { timeout: 30_000 });
	await expect(page.locator('.cite.cite-check')).toHaveCount(1);
});

test('a question with no recording gets an honest reply, not a made-up answer', async ({ page }) => {
	await open(page, 'chat');
	const box = page.getByRole('textbox', { name: 'Message' });
	await box.fill('What is the capital of Mongolia?');
	await box.press('Enter');
	const answer = page.locator('.prose.answer').last();
	await expect(answer).toContainText('recorded answers', { timeout: 20_000 });
	await expect(page.locator('.cite')).toHaveCount(0);
});

test('navigation stays inside the demo, and deep links survive a reload', async ({ page }) => {
	await open(page);
	await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Library' }).click();
	await expect(page).toHaveURL(/\/mimi\/demo\/library$/);
	await page.getByText('Medical Library').first().click();
	await expect(page).toHaveURL(/\/mimi\/demo\/library\/book\//);
	await expect(page.getByText('Where There Is No Doctor')).toBeVisible();
	await page.reload();
	await page.waitForFunction(() => !document.getElementById('boot'));
	await expect(page).toHaveURL(/\/mimi\/demo\/library\/book\//);
	await expect(page.getByText('Where There Is No Doctor')).toBeVisible();
	await open(page, 'settings/models'); // an old settings slug, through the 404 fallback and the redirect
	await expect(page).toHaveURL(/\/mimi\/demo\/settings\/intelligence#models$/);
});

test('switching the theme works for the session', async ({ page }) => {
	await open(page, 'settings/appearance');
	await page.getByRole('radio', { name: /Daylight|Light/ }).first().click();
	await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
});

for (const path of ['', 'library', 'chat']) {
	test(`no serious accessibility violations on /${path} with the banner`, async ({ page }) => {
		await open(page, path);
		await page.waitForLoadState('networkidle');
		const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
		const serious = r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
		expect(serious.map((v) => `${v.id}: ${v.help} ${v.nodes[0]?.target}`)).toEqual([]);
	});
}
