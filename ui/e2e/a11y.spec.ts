import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { ask, mode, setTheme, signIn } from './helpers';

// Automated WCAG 2.2 A/AA checks on every main screen, in both themes. Axe catches roughly a
// third of real accessibility problems; the rest are covered by design (docs/DESIGN_SYSTEM.md)
// and by the keyboard and screen-reader tests in the other specs.
const SCREENS = ['/', '/library', '/library/book/zimgit-medicine_en', '/library/read/wikimed/A/Hypothermia', '/settings/appearance', '/memory'];

for (const theme of ['dark', 'light'] as const) {
	test.describe(`${theme} theme`, () => {
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

		for (const url of SCREENS) {
			test(`no serious violations on ${url}`, async ({ page }) => {
				await page.goto(url);
				await page.waitForLoadState('networkidle');
				await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
				const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
				const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
				expect(serious.map((v) => `${v.id}: ${v.help} (${v.nodes.length}) ${v.nodes[0]?.target}`)).toEqual([]);
			});
		}

		test('no serious violations in an answered chat', async ({ page }) => {
			await mode(page, 'ungrounded');
			await page.goto('/chat');
			await ask(page, 'How do you treat hypothermia?');
			await expect(page.locator('.prose.answer').last()).toContainText('get help', { timeout: 20_000 });
			const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
			const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
			expect(serious.map((v) => `${v.id}: ${v.help} (${v.nodes.length}) ${v.nodes[0]?.target}`)).toEqual([]);
		});
	});
}
