import { expect, test } from '@playwright/test';
import { ask, mode, signIn, watchErrors } from './helpers';

test.describe('chat', () => {
	test('sources and a quoted passage arrive before the answer; citations open the source', async ({ page }) => {
		const errors = watchErrors(page);
		await mode(page, 'grounded');
		await signIn(page, '/chat');
		await ask(page, 'How do you treat hypothermia?');

		const answer = page.locator('.prose.answer').last();
		// while Mimi reads: the sources and the verbatim excerpt are already there, the answer isn't
		await expect(page.getByText('From the source').first()).toBeVisible();
		await expect(page.getByText('Hypothermia', { exact: true }).first()).toBeVisible();
		await expect(page.getByText(/not Mimi.s answer/)).toBeVisible();

		await expect(answer).toContainText('Warm the person gradually', { timeout: 20_000 });
		await expect(answer).toContainText('get help as fast as you can');
		await expect(page.locator('.cite').first()).toBeVisible();
		// a supported answer raises no citation warnings
		await expect(page.locator('.cite-check')).toHaveCount(0);
		await expect(page.getByText(/couldn't be matched/)).toHaveCount(0);
		await expect(page.getByText('Gemma 4 12B')).toBeVisible();

		await page.locator('.cite[data-cite="1"]').first().click();
		await expect(page).toHaveURL(/\/library\/read\/wikimed\//);
		expect(errors).toEqual([]);
	});

	test('a claim its source does not support is flagged, and the answer is left intact', async ({ page }) => {
		await mode(page, 'ungrounded');
		await signIn(page, '/chat');
		await ask(page, 'How do you treat hypothermia?');
		const answer = page.locator('.prose.answer').last();
		await expect(answer).toContainText('45 °C for 3 hours', { timeout: 20_000 });

		const flagged = page.locator('.cite.cite-check');
		await expect(flagged).toHaveCount(1);
		await expect(flagged).toHaveAttribute('aria-label', /may not say this/);
		const note = page.locator('details.checkcite');
		await expect(note).toContainText("1 cited claim couldn't be matched to its source");
		await note.locator('summary').click();
		await expect(note).toContainText('45 °C');
		await expect(note).toContainText(/number/);
		// the rest of the answer is untouched
		await expect(answer).toContainText('Warm the person gradually');
	});

	test('a failed answer can be retried', async ({ page }) => {
		await mode(page, 'error');
		await signIn(page, '/chat');
		await ask(page, 'How do you treat hypothermia?');
		await expect(page.getByRole('alert').filter({ hasText: 'stopped responding' })).toBeVisible();
		await mode(page, 'chitchat');
		await page.getByRole('button', { name: 'Try again' }).click();
		await expect(page.locator('.prose.answer').last()).toContainText("I'm here, all offline", { timeout: 15_000 });
	});
});
