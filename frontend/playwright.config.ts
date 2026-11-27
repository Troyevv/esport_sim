import { defineConfig } from '@playwright/test';

const baseURL = 'http://127.0.0.1:8766';
const devices = [
  { name: 'desktop', width: 1440, height: 960, touch: false },
  { name: 'phone-portrait', width: 390, height: 844, touch: true },
  { name: 'phone-landscape', width: 844, height: 390, touch: true },
  { name: 'tablet-portrait', width: 820, height: 1180, touch: true },
  { name: 'tablet-landscape', width: 1180, height: 820, touch: true },
];

export default defineConfig({
  testDir: './e2e',
  // The clients exercise the same single-player server and shared save slot.
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 12_000 },
  use: {
    baseURL,
    browserName: 'chromium',
    locale: 'ru-RU',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    launchOptions: {
      executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,
    },
  },
  projects: [...devices.map(({name, width, height, touch}) => ({
    name,
    grepInvert: {
      desktop: /@reconnect/,
      'phone-portrait': /@receipts/,
    }[name] ?? /@reconnect|@receipts/,
    use: { viewport: { width, height }, hasTouch: touch, isMobile: touch },
  })), {
    name: 'desktop-portrait', testMatch: 'scouting.spec.ts',
    use: {viewport: {width: 960, height: 1440}, hasTouch: false},
  }],
  webServer: {
    command: 'python frontend/e2e/serve.py',
    cwd: '..',
    url: baseURL,
    reuseExistingServer: false,
    timeout: process.env.CI ? 90_000 : 30_000,
  },
});
