import { expect, test } from '@playwright/test';
import { signIn } from './helpers';

test('old settings links still land in the right place', async ({ page }) => {
	await signIn(page, '/settings/models');
	await expect(page).toHaveURL(/\/settings\/intelligence#models$/);
	await page.goto('/settings/power');
	await expect(page).toHaveURL(/\/settings\/device#power$/);
});

test('the command palette lists every settings section, including Tools', async ({ page }) => {
	await signIn(page, '/');
	await page.keyboard.press('Control+k');
	const dialog = page.getByRole('dialog');
	await expect(dialog).toBeVisible();
	await dialog.getByRole('combobox').fill('tools');
	await expect(dialog.getByRole('option', { name: /Tools/ }).first()).toBeVisible();
	await page.keyboard.press('Escape');
	await expect(dialog).toBeHidden();
});
