import { expect, test, type Page } from '@playwright/test';
import { ask, mode, setTheme, signIn } from './helpers';

// Pixel snapshots of the screens people judge Mimi by. They catch the class of bug that type
// checks can't: a lost space before a middot, a clipped card, a theme that forgot a colour.
// Update deliberately with `npm run test:e2e:update` and review the diff in the PR.

const clock = (page: Page) => [page.locator('.strip time, .strip .clock, .strip [data-clock]'), page.locator('.when, time')];

async function settle(page: Page) {
	await page.waitForLoadState('networkidle');
	await page.evaluate(() => document.fonts.ready);
	await page.addStyleTag({ content: '*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}canvas{visibility:hidden}' });
}

for (const theme of ['dark', 'light'] as const) {
	test.describe(`${theme}`, () => {
		test.beforeEach(async ({ page }) => {
			await signIn(page, '/');
			await setTheme(page, theme);
		});
		test.afterAll(async ({ browser }) => {
			const page = await browser.newPage();
			await signIn(page, '/');
			await setTheme(page, 'dark');
			await page.close();
		});

		test('library', async ({ page }) => {
			await page.goto('/library');
			await expect(page.getByText('Medical Library')).toBeVisible();
			await settle(page);
			await expect(page).toHaveScreenshot(`library-${theme}.png`, { mask: clock(page) });
		});

		test('document collection', async ({ page }) => {
			await page.goto('/library/book/zimgit-medicine_en');
			await expect(page.getByText('Where There Is No Doctor')).toBeVisible();
			await settle(page);
			await expect(page).toHaveScreenshot(`collection-${theme}.png`, { mask: clock(page) });
		});

		test('answer with a flagged citation', async ({ page }) => {
			await mode(page, 'ungrounded');
			await page.goto('/chat');
			await ask(page, 'How do you treat hypothermia?');
			await expect(page.locator('details.checkcite')).toBeVisible({ timeout: 20_000 });
			await page.locator('details.checkcite summary').click();
			await settle(page);
			await expect(page).toHaveScreenshot(`chat-flagged-${theme}.png`, { mask: [...clock(page), page.locator('aside.list')] });
		});

		test('settings', async ({ page }) => {
			await page.goto('/settings/appearance');
			await settle(page);
			await expect(page).toHaveScreenshot(`settings-appearance-${theme}.png`, { mask: clock(page) });
		});
	});
}
