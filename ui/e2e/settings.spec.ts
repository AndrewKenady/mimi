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
	await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible();
	await page.keyboard.press('Control+k');
	const dialog = page.getByRole('dialog');
	await expect(dialog).toBeVisible();
	await dialog.getByRole('combobox').fill('tools');
	await expect(dialog.getByRole('option', { name: /Tools/ }).first()).toBeVisible();
	await page.keyboard.press('Escape');
	await expect(dialog).toBeHidden();
});

test('a profile whose model is missing names the pack that adds it', async ({ page }) => {
	await signIn(page, '/settings/intelligence');
	const note = page.locator('.warn-line', { hasText: "model isn't installed" });
	await expect(note).toHaveCount(0); // the hardware picked Standard, and Gemma 4 12B is answering
	await page.getByRole('radio', { name: 'Plus' }).click();
	await expect(note).toContainText("The Plus model isn't installed, so Mimi is using Gemma 4 12B");
	await expect(note).toContainText('content add llm-plus');
	await page.getByRole('radio', { name: /^Auto/ }).click();
	await expect(note).toHaveCount(0);
});
