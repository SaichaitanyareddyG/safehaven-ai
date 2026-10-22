import { defineConfig, devices } from '@playwright/test'

// End-to-end tests against a running backend (LLM_PROVIDER=mock, open
// self-registration) and dashboard. Locally: start both, then `npm run e2e`.
// CI starts them itself (.github/workflows/ci.yml, job "e2e").
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['list']] : 'list',
  use: {
    baseURL: process.env.E2E_WEB_URL ?? 'http://localhost:5173',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] }, testMatch: /staff\..*spec\.ts/ },
    { name: 'phone', use: { ...devices['Pixel 7'] }, testMatch: /patient\..*spec\.ts/ },
  ],
})
