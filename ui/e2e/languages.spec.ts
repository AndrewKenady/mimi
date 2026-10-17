import { expect, test } from '@playwright/test';
import { signIn } from './helpers';

// The whole interface follows the per-person Language setting; English stays the default.
test('the interface switches to Spanish and French, and back', async ({ page }) => {
	await signIn(page);
	const nav = page.getByRole('navigation', { name: /Main|Principal/ });
	await expect(nav.getByRole('link', { name: 'Library' })).toBeVisible();

	for (const [lang, library, settings, missing] of [
		['es', 'Biblioteca', 'Configuración', 'Ese libro no está en la biblioteca sin conexión.'],
		['fr', 'Bibliothèque', 'Paramètres', 'Ce livre n’est pas dans la bibliothèque hors ligne.']
	]) {
		const r = await page.request.patch('/api/settings/user/appearance', { data: { language: lang } });
		expect(r.ok()).toBeTruthy();
		await page.reload();
		await page.waitForFunction(() => !document.getElementById('boot'));
		await expect(page.locator('html')).toHaveAttribute('lang', lang);
		await expect(page.getByRole('link', { name: library }).first()).toBeVisible();
		await page.goto('/settings/appearance');
		await expect(page.getByRole('heading', { level: 1, name: settings })).toBeVisible();
		// Core words its own messages in the same language
		const err = await page.request.get('/api/library/collection/no-such-book', { headers: { 'x-mimi-locale': lang } });
		expect(err.status()).toBe(404);
		expect((await err.json()).detail).toBe(missing);
	}

	await page.request.patch('/api/settings/user/appearance', { data: { language: 'auto' } });
	await page.reload();
	await expect(page.locator('html')).toHaveAttribute('lang', 'en');
});
