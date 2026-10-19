import { defineConfig, devices } from '@playwright/test';

const real = process.env.E2E_REAL === '1';
export default defineConfig({
  testDir: './tests/e2e',
  testMatch: real ? ['proxy-routing.spec.ts', 'real-flow.spec.ts'] : 'ui-*.spec.ts',
  fullyParallel: true,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: process.env.BASE_URL ?? (real ? 'http://localhost:8080' : 'http://127.0.0.1:4173'),
    // Не сохраняем auth cookie/PII в trace или видео.
    trace: 'off',
    video: 'off',
    screenshot: 'off',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 } },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'], viewport: { width: 1440, height: 1000 } },
    },
    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'], viewport: { width: 1440, height: 1000 } },
    },
  ],
  webServer:
    !real && !process.env.BASE_URL
      ? {
          command: 'node tests/e2e/serve-spa.mjs',
          url: 'http://127.0.0.1:4173',
          reuseExistingServer: false,
        }
      : undefined,
});
