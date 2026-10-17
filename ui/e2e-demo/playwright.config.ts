import { defineConfig, devices } from '@playwright/test';

// The browser demo (npm run build:demo), served the way GitHub Pages serves it: the site at
// /mimi/, the demo at /mimi/demo/, unknown paths answered by site/404.html.
const PORT = Number(process.env.MIMI_DEMO_PORT || 7690);

export default defineConfig({
	testDir: '.',
	testMatch: '*.spec.ts',
	timeout: 45_000,
	expect: { timeout: 15_000 },
	workers: 1,
	retries: process.env.CI ? 1 : 0,
	reporter: process.env.CI ? [['github'], ['html', { open: 'never', outputFolder: '../playwright-report-demo' }]] : [['list']],
	outputDir: '../test-results-demo',
	use: { baseURL: `http://127.0.0.1:${PORT}`, viewport: { width: 1280, height: 800 }, trace: 'retain-on-failure' },
	projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } } }],
	webServer: { command: `node e2e-demo/serve.mjs ${PORT}`, url: `http://127.0.0.1:${PORT}/mimi/demo/`, reuseExistingServer: !process.env.CI, timeout: 30_000, cwd: '..' }
});
