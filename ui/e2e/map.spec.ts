import { expect, test, type Page } from '@playwright/test';
import { signIn, watchErrors } from './helpers';

// The fixture has no map data, so the map's own answers are stubbed here with places from a
// real OpenStreetMap build (central Vaduz). What's under test is how the map shows them.
const VADUZ = { lat: 47.1399, lon: 9.5215 };
const HOSPITAL = {
	name: 'Liechtensteinisches Landesspital', kind: 'hospital', lat: 47.1335, lon: 9.5207, distance_km: 0.71, direction: 'S',
	source: 'osm', osm: 'w32514862', emergency: 'yes', phone: '+423 235 44 11', address: 'Heiligkreuz 25, 9490 Vaduz',
	opening_hours: '24/7', unnamed: false
};
const FUEL = { name: 'Fuel station', kind: 'fuel', lat: 47.1421, lon: 9.5178, distance_km: 0.41, direction: 'NW', source: 'osm', unnamed: true };

/** `installed`: the device has the services data; `here`: it covers this spot (else hospitals come from GeoNames). */
async function stubMap(page: Page, installed: boolean, here = installed) {
	await page.route('**/api/maps/info', (r) => r.fulfill({ json: { tiles: false, regions: [], addresses: false, services: installed } }));
	await page.route('**/api/location/nearby?*', (r) => {
		const kind = new URL(r.request().url()).searchParams.get('kind');
		const places = kind === 'hospital' ? [HOSPITAL] : kind === 'fuel' && here ? [FUEL] : [];
		return r.fulfill({ json: { places, location: VADUZ, services: here } });
	});
}

// later tests (and their screenshots) expect no location and English
test.afterEach(async ({ page }) => {
	await page.request.delete('/api/location/manual');
	await page.request.patch('/api/settings/user/appearance', { data: { language: 'auto' } });
});

test('fuel stations and hospitals near me, with what OpenStreetMap knows about them', async ({ page }) => {
	const errors = watchErrors(page);
	await signIn(page);
	expect((await page.request.post('/api/location', { data: { ...VADUZ, label: 'Vaduz', manual: true } })).ok()).toBeTruthy();
	await stubMap(page, true);
	await page.goto('/map');

	await page.getByRole('button', { name: 'Hospitals' }).click();
	await expect(page.getByText('Nearest', { exact: true })).toBeVisible();
	await expect(page.getByText(/From OpenStreetMap, as mapped\..*In an emergency, call the local emergency number first\./)).toBeVisible();
	await page.getByRole('button', { name: /Liechtensteinisches Landesspital/ }).click();
	const card = page.locator('.sel');
	await expect(card.getByText('Emergency department', { exact: true })).toBeVisible();
	await expect(card.getByText('Heiligkreuz 25, 9490 Vaduz')).toBeVisible();
	await expect(card.getByRole('link', { name: '+423 235 44 11' })).toHaveAttribute('href', 'tel:+4232354411');

	// a station mapped without a name is called what it is, in the interface language
	await page.getByRole('button', { name: 'Fuel' }).click();
	await expect(page.locator('.place .pn')).toHaveText(['Fuel station']);
	await page.request.patch('/api/settings/user/appearance', { data: { language: 'es' } });
	await page.reload();
	await page.getByRole('button', { name: 'Gasolineras' }).click();
	await expect(page.locator('.place .pn')).toHaveText(['Gasolinera']);
	expect(errors).toEqual([]);
});

test('outside the services data, the map says its list may be incomplete', async ({ page }) => {
	await signIn(page);
	expect((await page.request.post('/api/location', { data: { ...VADUZ, label: 'Vaduz', manual: true } })).ok()).toBeTruthy();
	await stubMap(page, true, false);
	await page.goto('/map');
	await page.getByRole('button', { name: 'Hospitals' }).click();
	await expect(page.getByText(/No detailed data for this area, so this list may be incomplete\./)).toBeVisible();
	await page.getByRole('button', { name: 'Fuel' }).click();
	await expect(page.getByText('None in the offline map data within 250 km.')).toBeVisible();
});

test('without the services data, the map offers no service filters', async ({ page }) => {
	await signIn(page);
	expect((await page.request.post('/api/location', { data: { ...VADUZ, label: 'Vaduz', manual: true } })).ok()).toBeTruthy();
	await stubMap(page, false);
	await page.goto('/map');
	await expect(page.getByRole('button', { name: 'Nature' })).toBeVisible();
	for (const name of ['Fuel', 'Hospitals', 'Pharmacies']) await expect(page.getByRole('button', { name })).toHaveCount(0);
});
