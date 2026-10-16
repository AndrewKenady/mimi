import { expect, test } from '@playwright/test';
import { signIn, watchErrors } from './helpers';

// Regression for the bug that started this work: document collections (PDF "nautilus" ZIMs)
// were listed as available but opened to a blank page. Every book must either open to real
// content or say plainly why it can't.

test('every card shows an honest status', async ({ page }) => {
	const errors = watchErrors(page);
	await signIn(page, '/library');
	const card = (name: string) => page.locator('a, button, article, div').filter({ hasText: name }).last();
	await expect(page.getByText('Medical Library')).toBeVisible();
	await expect(card('Medical Library')).toContainText('12 documents');
	await expect(card('Medical Library')).toContainText('Ready');
	await expect(card('TED Medicine')).toContainText('Browse only');
	await expect(card('Project Gutenberg: Classics')).toContainText("Can't open");
	await expect(card('Project Gutenberg: Classics')).toContainText('damaged');
	// the header counts documents, not the "1 article" a nautilus ZIM reports, and the middot keeps its space
	await expect(page.locator('.page-sub')).toContainText('12 documents');
	// a download that stopped halfway isn't on the shelf, and the owner is told which and how far it got
	const held = page.getByRole('status').filter({ hasText: "didn't finish downloading" });
	await expect(held).toContainText('wiktionary_en_all_nopic_2026-07.zim');
	await expect(held).toContainText('of 8.9 GB');
	await expect(page.locator('body')).not.toContainText(/\d(articles|documents)·/);
	expect(errors).toEqual([]);
});

test('a document collection opens to a list of its books, not a blank page', async ({ page }) => {
	await signIn(page, '/library');
	await page.getByText('Medical Library').first().click();
	await expect(page).toHaveURL(/\/library\/book\//);
	await expect(page.getByRole('heading', { name: 'Medical Library' })).toBeVisible();
	for (const t of ['Where There Is No Doctor', 'First Aid', 'Wound Closure Manual']) await expect(page.getByText(t, { exact: true })).toBeVisible();
	await expect(page.getByText(/446 pages/).first()).toBeVisible();
	await page.getByPlaceholder(/filter/i).fill('doctor');
	await expect(page.getByText('First Aid', { exact: true })).toBeHidden();
	await expect(page.getByText('Where There Is No Doctor', { exact: true })).toBeVisible();
});

test('an article opens in the reader with its contents', async ({ page }) => {
	await signIn(page, '/library/read/wikimed/A/Hypothermia');
	await expect(page.getByRole('heading', { name: 'Hypothermia', level: 1 })).toBeVisible();
	await expect(page.getByText('Treatment of mild hypothermia involves warm drinks')).toBeVisible();
	await expect(page.getByRole('button', { name: /ask mimi/i })).toBeVisible();
});
