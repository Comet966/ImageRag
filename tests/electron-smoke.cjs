const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs/promises');
const { pathToFileURL } = require('node:url');
const { _electron: electron } = require('playwright');

async function main() {
  const root = path.resolve(__dirname, '..');
  const manifest = JSON.parse(await fs.readFile(path.join(root, 'data/manifest.json'), 'utf8'));
  const count = manifest.photos.length;
  assert.equal(count, 300);
  const env = { ...process.env, IMAGERAG_E2E: '1', IMAGERAG_NO_API: '1' };
  delete env.ELECTRON_RUN_AS_NODE;
  const app = await electron.launch({ args: [root], env, timeout: 30000 });
  const errors = [];
  try {
    const page = await app.firstWindow();
    page.on('pageerror', (error) => errors.push(error.message));
    await page.waitForFunction((count) => document.querySelector('#connection').textContent === `${count} / ${count} 张已就绪`, count, { timeout: 30000 });
    assert.equal(await page.locator('.photo-card').count(), count);
    const security = await app.evaluate(({ BrowserWindow }) => {
      const preferences = BrowserWindow.getAllWindows()[0].webContents.getLastWebPreferences();
      return { sandbox: preferences.sandbox, contextIsolation: preferences.contextIsolation, nodeIntegration: preferences.nodeIntegration };
    });
    assert.deepEqual(security, { sandbox: true, contextIsolation: true, nodeIntegration: false });
    assert.equal(await page.evaluate(() => typeof window.require), 'undefined');

    const beforeRun = await page.evaluate(() => window.imageLibrary.status());
    assert.deepEqual(beforeRun.media_types, { photo: 140, screenshot: 80, illustration: 80 });
    await page.locator('[data-media-type="screenshot"]').click();
    assert.equal(await page.locator('.photo-card').count(), 80);
    await page.locator('[data-media-type="illustration"]').click();
    assert.equal(await page.locator('.photo-card').count(), 80);
    await page.locator('[data-media-type="photo"]').click();
    assert.equal(await page.locator('.photo-card').count(), 140);
    await page.locator('[data-media-type="all"]').click();
    assert.equal(await page.locator('.photo-card').count(), count);
    await page.waitForFunction(() => [...document.querySelectorAll('.photo-card img')].slice(0, 12).every((image) => image.complete && image.naturalWidth > 0));
    await page.screenshot({ path: path.join(root, 'outputs', 'electron-library-300.png') });
    // Reuse real API-produced cached vectors. This test must never spend tokens.
    const query = '一杯咖啡';
    await page.getByRole('textbox', { name: '用自然语言描述图片' }).fill(query);
    await page.getByRole('button', { name: '搜索图片', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#gallery-title').textContent.includes('一杯咖啡'));
    assert.equal(await page.locator('.photo-card').count(), 12);
    const firstTitle = await page.locator('.photo-title').first().textContent();
    assert.match(firstTitle, /咖啡杯/);
    assert.match(await page.locator('#gallery-info').textContent(), /本次未调用模型/);
    await page.waitForFunction(() => [...document.querySelectorAll('.photo-card img')].every((image) => image.complete && image.naturalWidth > 0));
    await fs.mkdir(path.join(root, 'outputs'), { recursive: true });
    await page.screenshot({ path: path.join(root, 'outputs', 'electron-search-coffee.png') });
    const firstId = await page.locator('.photo-card').first().getAttribute('data-id');
    await page.locator('.photo-card').first().click();
    await page.locator('#photo-dialog').waitFor({ state: 'visible' });
    await page.waitForFunction(() => document.querySelector('#detail-image').naturalWidth >= 1000);
    await page.screenshot({ path: path.join(root, 'outputs', 'electron-photo-detail.png') });
    await page.getByRole('button', { name: '关闭图片详情' }).click();

    await page.getByRole('button', { name: '一架飞机', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#gallery-title').textContent.includes('一架飞机'));
    assert.match(await page.locator('.photo-title').first().textContent(), /飞机/);
    await page.getByRole('button', { name: '查看全部', exact: true }).click();
    assert.equal(await page.locator('.photo-card').count(), count);
    const typedCases = [
      { type: 'photo', query: '一把雨伞', expected: /雨伞/, image: 'electron-search-photo.png' },
      { type: 'screenshot', query: '手机上的应用界面截图', expected: /应用截图/, image: 'electron-search-screenshot.png' },
      { type: 'illustration', query: '卡通漫画', expected: /漫画/, image: 'electron-search-illustration.png' },
    ];
    for (const item of typedCases) {
      await page.locator(`[data-media-type="${item.type}"]`).click();
      await page.getByRole('textbox', { name: '用自然语言描述图片' }).fill(item.query);
      await page.getByRole('button', { name: '搜索图片', exact: true }).click();
      await page.waitForFunction((query) => document.querySelector('#gallery-title').textContent.includes(query), item.query);
      await page.waitForFunction(() => !document.querySelector('#search-button').disabled);
      assert.match(await page.locator('.photo-title').first().textContent(), item.expected);
      const id = await page.locator('.photo-card').first().getAttribute('data-id');
      assert.equal(manifest.photos.find((photo) => photo.id === id).media_type, item.type);
      await page.waitForFunction(() => [...document.querySelectorAll('.photo-card img')].every((image) => image.complete && image.naturalWidth > 0));
      await page.screenshot({ path: path.join(root, 'outputs', item.image) });
      await page.getByRole('button', { name: '查看全部', exact: true }).click();
    }
    // No confirmation dialog: an uncached request reaches the offline guard directly.
    await page.getByRole('textbox', { name: '用自然语言描述图片' }).fill('离线验收专用：一杯带有拉花的咖啡');
    await page.getByRole('button', { name: '搜索图片', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('离线验收模式'));
    assert.equal(await page.locator('#billing-dialog').count(), 0);
    assert.equal(await page.locator('.photo-card').count(), count);
    await page.waitForFunction(() => !document.querySelector('#search-button').disabled);
    const before = await page.evaluate(() => window.imageLibrary.status());
    await page.getByRole('button', { name: '检查索引', exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('#index-button').disabled);
    const after = await page.evaluate(() => window.imageLibrary.status());
    assert.equal(before.usage.calls, after.usage.calls, 'Resuming a complete index must not call the API again');
    assert.equal(beforeRun.usage.calls, after.usage.calls, 'The entire desktop test must make zero model requests');
    const denied = await page.evaluate(async () => {
      try { await window.imageLibrary.openSource('not-in-manifest'); return false; }
      catch { return true; }
    });
    assert.equal(denied, true);
    // Reproduce opening index.html in a browser: no preload, no imageLibrary.
    const previewCreated = app.waitForEvent('window');
    await app.evaluate(async ({ BrowserWindow }) => {
      globalThis.previewWindow = new BrowserWindow({ show: false, width: 1100, height: 850,
        webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
      await globalThis.previewWindow.loadURL('about:blank');
    });
    const preview = await previewCreated;
    const previewErrors = [];
    preview.on('pageerror', (error) => previewErrors.push(error.message));
    const previewUrl = pathToFileURL(path.join(root, 'renderer/index.html')).href;
    await preview.goto(previewUrl);
    await preview.waitForFunction(() => document.querySelector('#notice').textContent.includes('npm start'));
    assert.equal(await preview.evaluate(() => typeof window.imageLibrary), 'undefined');
    assert.equal(await preview.locator('#query').isDisabled(), true);
    assert.equal(await preview.locator('#search-button').isDisabled(), true);
    assert.equal(await preview.locator('#index-button').isDisabled(), true);
    assert.equal(await preview.locator('#refresh-button').isDisabled(), true);
    assert.equal(await preview.locator('[data-query]:not(:disabled)').count(), 0);
    await preview.locator('#search-form').dispatchEvent('submit');
    assert.equal(preview.url(), previewUrl);
    assert.deepEqual(previewErrors, []);
    await preview.screenshot({ path: path.join(root, 'outputs', 'browser-preview-startup-hint.png') });
    assert.deepEqual(errors, []);
    const report = {
      tested_at: new Date().toISOString(), electron: await app.evaluate(() => process.versions.electron),
      library_count: count, query, first_result_id: firstId, first_result_title: firstTitle,
      mode: 'Offline UI replay using real API-produced cached embeddings; no new model calls',
      model_calls_during_test: after.usage.calls - beforeRun.usage.calls,
      passed: ['desktop startup', '300 mixed photos, screenshots and illustrations', 'Chinese query through IPC and actual cached embeddings', '12 decoded result thumbnails', '1024px original in modal', 'example query', 'reset to gallery', 'media-type constrained search for photos, screenshots and illustrations', 'direct call without cost confirmation; offline guard prevents network', 'idempotent indexing', 'renderer isolation', 'invalid source rejected', 'browser file preview shows startup instructions instead of undefined API errors', 'browser preview disables unavailable actions and prevents form navigation'],
      screenshots: ['outputs/electron-library-300.png', 'outputs/electron-search-coffee.png', 'outputs/electron-search-photo.png', 'outputs/electron-search-screenshot.png', 'outputs/electron-search-illustration.png', 'outputs/electron-photo-detail.png', 'outputs/browser-preview-startup-hint.png'],
      browser_preview_errors: previewErrors,
      page_errors: errors,
    };
    await fs.writeFile(path.join(root, 'outputs', 'electron-smoke.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
  } finally {
    await app.close();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
