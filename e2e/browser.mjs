/**
 * Real-browser end-to-end check of the triage console.
 *
 * This is not part of `npm test`. It needs a live backend, a live Vite dev
 * server and a real Chromium, which is why it is manual: it answers "does the
 * console actually work in a browser", a question jsdom + MSW cannot answer.
 *
 * Setup (three terminals):
 *
 *   1. backend      see docs/TESTING.md, with LLM_* pointed at any
 *                   OpenAI-compatible endpoint (a local stub is fine)
 *   2. frontend     cd frontend && npm run dev
 *   3. this script  npm i --no-save playwright && npx playwright install chromium
 *                   node e2e/browser.mjs
 *
 * Environment:
 *   E2E_BASE_URL     default http://localhost:5173
 *   E2E_USERNAME     default admin
 *   E2E_PASSWORD     default admin-password-123
 *   CHROME_PATH      optional, if playwright's bundled Chromium is unavailable
 *
 * It checks the path a human actually walks: login, filter, alert detail,
 * start an investigation, read the steps and the report, reload without losing
 * state, sign out. Any console error or uncaught page error fails the run.
 */
import { chromium } from 'playwright';

const BASE = process.env.E2E_BASE_URL || 'http://localhost:5173';
const USERNAME = process.env.E2E_USERNAME || 'admin';
const PASSWORD = process.env.E2E_PASSWORD || 'admin-password-123';

const steps = [];
const problems = [];
const ok = (step, detail = '') =>
  steps.push(`  OK   ${step}${detail ? '  — ' + detail : ''}`);
const bad = (step, detail) => {
  steps.push(`  FAIL ${step}  — ${detail}`);
  problems.push(step);
};

const browser = await chromium.launch(
  process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {},
);
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });

page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`));
page.on('console', (message) => {
  if (message.type() === 'error') problems.push(`console: ${message.text()}`);
});

try {
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#username', { timeout: 15000 });
  ok('login page renders', page.url().replace(BASE, '') || '/');

  await page.fill('#username', USERNAME);
  await page.fill('#password', PASSWORD);
  await page.click('button[type="submit"]');
  // Login lands on the dashboard, not the alert list.
  await page.waitForSelector('text=安全运营仪表盘', { timeout: 15000 });
  ok('dashboard rendered after login', page.url().replace(BASE, '') || '/');

  await page.getByRole('link', { name: '告警' }).first().click();
  await page.waitForURL(/\/alerts/, { timeout: 15000 });
  await page.waitForSelector('table tbody tr', { timeout: 15000 });
  ok('alert list loaded', `${await page.locator('table tbody tr').count()} rows`);

  // Filtering must be a server round trip: the empty state proves the request
  // carried the filter rather than the client hiding rows.
  const statusSelect = page.locator('.sf-filter-bar select').first();
  await statusSelect.selectOption('closed');
  await page.waitForTimeout(900);
  if ((await page.locator('body').innerText()).includes('暂无告警')) {
    ok('status filter returns an empty state');
  } else {
    bad('status filter', 'expected the empty state for status=closed');
  }
  await statusSelect.selectOption('');
  await page.waitForTimeout(900);

  await page.locator('table tbody tr').first().click();
  await page.waitForURL(/\/alerts\/[0-9a-f-]{36}$/, { timeout: 15000 });
  await page.waitForSelector('text=告警信息', { timeout: 15000 });
  ok('alert detail page', page.url().replace(BASE, ''));
  if ((await page.locator('body').innerText()).includes('关联证据')) {
    ok('evidence preview rendered');
  } else {
    bad('evidence preview', 'missing 关联证据 card');
  }

  const start = page.getByRole('button', { name: /启动 AI 调查/ });
  if ((await start.count()) === 0) throw new Error('start button not found');
  await start.click();
  await page.waitForSelector('text=/排队中|进行中/', { timeout: 20000 });
  ok('investigation submitted');

  await page.waitForSelector('text=已完成', { timeout: 90000 });
  const done = await page.locator('body').innerText();
  ok('investigation finished');
  for (const [label, needle] of [
    ['steps table', '执行步骤'],
    ['tool calls', '工具调用'],
    ['report', '报告'],
  ]) {
    if (done.includes(needle)) ok(`${label} rendered`);
    else bad(label, `missing "${needle}"`);
  }

  if (/[?&]investigation=/.test(page.url())) {
    ok('investigation id persisted in the URL');
  } else {
    bad('url', `no investigation param: ${page.url()}`);
  }

  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForSelector('text=已完成', { timeout: 30000 });
  ok('after reload the investigation is restored');

  const reportLink = page.getByRole('link', { name: /查看报告|报告/ }).first();
  if ((await reportLink.count()) > 0) {
    await reportLink.click();
    await page.waitForURL(/\/report/, { timeout: 15000 });
    // The report is fetched after the route changes; wait for the badge.
    await page.waitForSelector('text=确定性规则生成', { timeout: 20000 });
    ok('report page labels the rule-generated report');
  }

  await page.getByRole('button', { name: /退出/ }).first().click();
  await page.waitForSelector('#username', { timeout: 15000 });
  ok('logout returns to the login page');

  await page.goto(BASE + '/alerts', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#username', { timeout: 15000 });
  ok('protected route redirects when signed out');
} catch (error) {
  bad('unexpected', String(error.message).split('\n')[0]);
  try {
    const shot = 'e2e/failure.png';
    await page.screenshot({ path: shot, fullPage: true });
    steps.push(`  (screenshot saved to ${shot})`);
  } catch {
    // The browser may already be gone; the step list is enough.
  }
} finally {
  await browser.close();
}

console.log(steps.join('\n'));
console.log();
if (problems.length) {
  console.log(`FAILURES (${problems.length}):`);
  for (const problem of problems) console.log('  - ' + problem);
  process.exit(1);
}
console.log('all browser checks passed');
