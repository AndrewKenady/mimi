import { defineConfig, devices } from '@playwright/test';

// End-to-end tests drive the built UI against the real Core API with a scripted model and a
// small fake library (e2e/fixture_core.py), so they run anywhere without models or content.
const PORT = Number(process.env.MIMI_E2E_PORT || 7671); // set MIMI_E2E_PORT to run two checkouts at once
const python = process.env.MIMI_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');

export default defineConfig({
	testDir: 'e2e',
	timeout: 30_000,
	expect: { timeout: 10_000, toHaveScreenshot: { maxDiffPixelRatio: 0.01, animations: 'disabled', caret: 'hide' } },
	fullyParallel: false, // one Core, one database: tests share it, so run them in order
	workers: 1,
	retries: process.env.CI ? 1 : 0,
	reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : [['list']],
	snapshotPathTemplate: '{testDir}/__screenshots__/{testFilePath}/{arg}{ext}',
	use: {
		baseURL: `http://127.0.0.1:${PORT}`,
		viewport: { width: 1280, height: 800 },
		trace: 'retain-on-failure',
		launchOptions: process.env.PLAYWRIGHT_CHROMIUM_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } : {}
	},
	projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } } }],
	webServer: {
		command: `${python} e2e/fixture_core.py --port ${PORT} --speed 8`,
		url: `http://127.0.0.1:${PORT}/api/bootstrap`,
		reuseExistingServer: !process.env.CI,
		timeout: 60_000
	}
});
