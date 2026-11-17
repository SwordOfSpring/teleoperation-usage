const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const customers = Array.from({ length: 18 }, (_, i) => ({ vid: String(i), company_name: '客户' + i }));
const rows = Array.from({ length: 16 }, (_, i) => customers.map((customer) => ({
  ...customer, date: '202611' + String(i + 1).padStart(2, '0'),
  total: (i + 1) * 100, host_total: (i + 1) * 70, viewer_total: (i + 1) * 30,
  audio_total: (i + 1) * 40, video_total: (i + 1) * 60,
}))).flat();
const payload = { customers, overview: rows, daily: rows };
const chart = '#overview-customer-total-chart';

async function openDashboard(browser, options = {}) {
  const page = await browser.newPage({ viewport: { width: 2200, height: 1000 }, ...options });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error' || message.type() === 'warning') errors.push(message.text());
  });
  await page.route('http://dashboard.test/**', async (route) => {
    const filename = new URL(route.request().url()).pathname.slice(1) || 'index.html';
    let body = fs.readFileSync(path.join(root, filename), 'utf8');
    if (filename === 'index.html') body = body.replace(
      /(<script id="teleoperation-data" type="application\/json">)[\s\S]*?(<\/script>)/,
      '$1' + JSON.stringify(payload) + '$2',
    );
    await route.fulfill({ body, contentType: filename.endsWith('.css') ? 'text/css' : filename.endsWith('.js') ? 'text/javascript' : 'text/html' });
  });
  await page.goto('http://dashboard.test/index.html');
  await page.locator(chart + ' svg').waitFor();
  assert.match(await page.title(), /用量/);
  assert.equal(await page.locator('#overview-view').isVisible(), true);
  await page.locator(chart).scrollIntoViewIfNeeded();
  return { page, errors };
}

async function position(page, date, fraction = 0, svgY = 120) {
  return page.locator(chart + ' svg').evaluate((svg, args) => {
    const labels = [...svg.querySelectorAll('text.chart-axis')];
    const label = labels.find((node) => node.textContent === args.date);
    const next = labels[labels.indexOf(label) + 1];
    const x = Number(label.getAttribute('x'));
    const nextX = next ? Number(next.getAttribute('x')) : x;
    const point = new DOMPoint(x + (nextX - x) * args.fraction, args.svgY).matrixTransform(svg.getScreenCTM());
    return { x: point.x, y: point.y };
  }, { date, fraction, svgY });
}

async function title(page) {
  const tooltip = page.locator(chart + ' .chart-tooltip');
  assert.equal(await tooltip.isVisible(), true);
  return tooltip.locator('.chart-tooltip-title').textContent();
}

async function assertAvoidsPointer(page, point) {
  const box = await page.locator(chart + ' .chart-tooltip').boundingBox();
  assert.ok(point.x < box.x || point.x > box.x + box.width || point.y < box.y || point.y > box.y + box.height, 'Tooltip must avoid the pointer');
  const viewport = page.viewportSize();
  assert.ok(box.x >= 0 && box.x + box.width <= viewport.width, 'Tooltip stays within the viewport');
  assert.ok(box.y >= 0 && box.y + box.height <= viewport.height, 'Tooltip stays within the viewport vertically');
}

test('chart tooltip interactions', async (t) => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    await t.test('hover selects the nearest date despite SVG side margins and avoids the pointer', async () => {
      const { page, errors } = await openDashboard(browser);
      try {
        for (const [date, fraction, expected] of [['11-14', 0.4, '11-14'], ['11-14', 0.6, '11-15'], ['11-01', 0, '11-01'], ['11-16', 0, '11-16']]) {
          const point = await position(page, date, fraction);
          await page.mouse.move(point.x, point.y);
          assert.equal(await title(page), expected);
          await assertAvoidsPointer(page, point);
          await assertAvoidsPointer(page, await position(page, expected));
        }
        await page.mouse.move(0, 0);
        assert.equal(await page.locator(chart + ' .chart-tooltip').isVisible(), false);
        assert.deepEqual(errors, []);
        if (process.env.CHART_SCREENSHOT_DIR) {
          const point = await position(page, '11-14', 0.4);
          await page.mouse.move(point.x, point.y);
          await page.screenshot({ path: path.join(process.env.CHART_SCREENSHOT_DIR, 'tooltip-desktop.png') });
        }
      } finally { await page.close(); }
    });
    await t.test('moving over a series line updates the date; leaving the plot clears it', async () => {
      const { page } = await openDashboard(browser);
      try {
        const start = await position(page, '11-12');
        await page.mouse.move(start.x, start.y);
        const point = page.locator(chart + ' .chart-point[data-index="13"]').first();
        const box = await point.boundingBox();
        await page.mouse.move(box.x + box.width / 2 - 8, box.y + box.height / 2);
        assert.equal(await title(page), '11-14');
        const label = await position(page, '11-14', 0, 310);
        await page.mouse.move(label.x, label.y);
        assert.equal(await page.locator(chart + ' .chart-tooltip').isVisible(), false);
      } finally { await page.close(); }
    });
    await t.test('click triggers the tooltip without prior hover; keyboard focus remains supported', async () => {
      const { page } = await openDashboard(browser);
      try {
        const point = await position(page, '11-15');
        await page.locator(chart + ' svg').dispatchEvent('click', { clientX: point.x, clientY: point.y });
        assert.equal(await title(page), '11-15');
        await page.locator(chart + ' .chart-point[data-index="13"]').first().focus();
        assert.equal(await title(page), '11-14');
        await page.keyboard.press('Escape');
        assert.equal(await page.locator(chart + ' .chart-tooltip').isVisible(), false);
      } finally { await page.close(); }
    });
    await t.test('a clicked tooltip can scroll long customer lists and closes outside the chart', async () => {
      const { page } = await openDashboard(browser);
      try {
        const point = await position(page, '11-14');
        await page.mouse.click(point.x, point.y);
        assert.equal(await title(page), '11-14');
        const tooltip = page.locator(chart + ' .chart-tooltip');
        const box = await tooltip.boundingBox();
        await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
        await page.mouse.wheel(0, 180);
        await page.waitForFunction((selector) => document.querySelector(selector).scrollTop > 0, chart + ' .chart-tooltip');
        assert.equal(await title(page), '11-14');
        await page.mouse.click(5, 5);
        assert.equal(await tooltip.isVisible(), false);
      } finally { await page.close(); }
    });
    await t.test('touch works on mobile, stays visible after release, and dismisses outside', async () => {
      const { page, errors } = await openDashboard(browser, { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
      try {
        const point = await position(page, '11-14');
        await page.touchscreen.tap(point.x, point.y);
        assert.equal(await title(page), '11-14');
        await assertAvoidsPointer(page, point);
        assert.deepEqual(errors, []);
        if (process.env.CHART_SCREENSHOT_DIR) await page.screenshot({ path: path.join(process.env.CHART_SCREENSHOT_DIR, 'tooltip-mobile.png') });
        await page.touchscreen.tap(5, 5);
        assert.equal(await page.locator(chart + ' .chart-tooltip').isVisible(), false);
      } finally { await page.close(); }
    });
  } finally { await browser.close(); }
});
