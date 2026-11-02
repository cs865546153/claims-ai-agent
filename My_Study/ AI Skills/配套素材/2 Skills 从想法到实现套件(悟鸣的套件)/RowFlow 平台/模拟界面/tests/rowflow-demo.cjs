/* Browser integration checks for the offline teaching interface. No server needed. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const root = path.resolve(__dirname, '..');
const entry = path.join(root, 'rowflow-demo.html');
const reportDir = process.env.ROWFLOW_QA_DIR ? path.resolve(root, process.env.ROWFLOW_QA_DIR) : path.join(root, '.spec-to-ship/rowflow-ui');
const screenshotDir = path.join(reportDir, 'screenshots');
fs.mkdirSync(screenshotDir, { recursive: true });
const source = fs.readFileSync(entry, 'utf8');
const payload = JSON.parse(source.match(/<script id="platform-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
const checks = [];
const errors = [];
const remoteRequests = [];
const passed = (name, evidence) => { checks.push({ name, result: 'pass', evidence }); console.log('PASS ' + name); };

async function main() {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1080 }, deviceScaleFactor: 1 });
    page.on('pageerror', e => errors.push(e.message));
    page.on('request', req => { if (/^https?:/.test(req.url())) remoteRequests.push(req.url()); });
    await page.goto(pathToFileURL(entry).href);
    await page.waitForTimeout(300);
    assert.equal(await page.title(), 'RowFlow · 数据编排');
    assert.equal(payload.docs.length, 16);
    assert.equal(payload.faq.length, 24);
    const examples = [...fs.readFileSync(path.join(root, '11-完整脚本示例.md'), 'utf8').matchAll(/^```groovy\n([\s\S]*?)^```\s*$/gm)].map(m => m[1].trim());
    assert.equal(payload.scripts.city.trim(), examples[2]);
    assert.equal(payload.scripts.http.trim(), examples[1]);
    assert.equal(payload.scripts.lookup.trim(), examples[3]);
    passed('UI-01 离线加载与嵌入数据', 'file:// 打开；16 文档、24 FAQ，3 份完整脚本与原文一致');

    const result = () => page.locator('#resultJson').textContent().then(JSON.parse);
    const simulate = async () => {
      await page.locator('#runBtn').click();
      assert.equal(await page.locator('#runBtn').isDisabled(), true);
      await page.waitForFunction(() => !document.getElementById('runBtn').disabled);
    };
    assert.deepEqual(await result(), [
      { city: '杭州', orderCount: 3, totalAmount: 370.5, averageAmount: 123.5 },
      { city: '未知', orderCount: 1, totalAmount: 100, averageAmount: 100 }
    ]);
    await page.locator('[data-node="aggregate"]').click();
    assert.match(await page.locator('#rowMap').textContent(), /370.5/);
    await page.locator('[data-source="orders"]').first().click();
    assert.equal(await page.locator('#contentModal').evaluate(el => el.open), true);
    assert.match(await page.locator('#modalBody').textContent(), /data.items/);
    await page.locator('[data-source-tab="response"]').click();
    assert.match(await page.locator('#modalBody').textContent(), /O1005/);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#contentModal').evaluate(el => el.open), false);
    await simulate();
    assert.match(await page.locator('#resultLogs').textContent(), /先读取 RPC users/);
    assert.match(await page.locator('#resultLogs').textContent(), /请求 2 次/);
    assert.equal(await page.locator('#historyCount').textContent(), '1');
    passed('UI-02 / UI-03 数据流、Row、源详情与正常统计', '杭州 370.50 + 未知 100.00；2 次请求；源弹窗可切换与关闭');

    await page.locator('#fixtureSelect').selectOption('empty');
    assert.deepEqual(await result(), []);
    assert.match(await page.locator('[data-node="filter"]').textContent(), /0 行/);
    await simulate();
    assert.match(await page.locator('#resultLogs').textContent(), /请求 2 次/);
    await page.locator('#fixtureSelect').selectOption('malformed');
    await simulate();
    assert.equal((await result()).code, 'RF-SRC-003');
    assert.match(await page.locator('#resultLogs').textContent(), /没有部分业务结果/);
    await page.locator('#fixtureSelect').selectOption('normal');
    await simulate();
    assert.equal((await result()).length, 2);
    passed('UI-04 扫描输入空值、错误与恢复', '空输入 []；用户表结构错误 RF-SRC-003；切回正常后成功');

    await page.locator('#scenarioSelect').selectOption('http');
    assert.deepEqual((await result()).map(o => o.orderId), ['O1003', 'O1001', 'O1005']);
    await page.locator('#threshold').fill('150');
    assert.deepEqual((await result()).map(o => o.orderId), ['O1003']);
    await page.locator('#threshold').fill('0');
    assert.equal((await result()).length, 4);
    await page.locator('#threshold').fill('-1');
    assert.match(await page.locator('#resultSummary').textContent(), /参数待修正/);
    await page.locator('#runBtn').click();
    assert.match(await page.locator('#toast').textContent(), /金额/);
    assert.equal(await page.locator('#runBtn').isDisabled(), false);
    await page.locator('#threshold').fill('100');
    await simulate();
    assert.equal((await result()).length, 3);
    passed('UI-03 / UI-04 HTTP 参数边界与排序', '100 元时 3 条；150 元时 1 条；0 元时 4 条；负值阻止模拟并可恢复');

    await page.locator('#scenarioSelect').selectOption('lookup');
    await simulate();
    assert.equal((await result()).length, 4);
    assert.match(await page.locator('#resultFooter').textContent(), /正常未命中 1 行 · 错误降级 0 行/);
    assert.match(await page.locator('#resultLogs').textContent(), /共 4 次查询/);
    await page.locator('#fixtureSelect').selectOption('timeout');
    await simulate();
    assert.equal((await result())[2].city, '未知');
    assert.match(await page.locator('#resultFooter').textContent(), /正常未命中 1 行 · 错误降级 1 行/);
    await page.locator('#fixtureSelect').selectOption('empty');
    await simulate();
    assert.deepEqual(await result(), []);
    assert.match(await page.locator('#resultLogs').textContent(), /共 0 次查询/);
    passed('UI-03 / UI-04 lookup 未命中、降级与调用次数', '重复用户仍调用；超时不丢订单；正常未命中与错误降级分别计数');

    await page.locator('#fullTab').click();
    await page.locator('#codeInput').fill(payload.scripts.lookup + '// custom change\n');
    await page.locator('#runBtn').click();
    assert.match(await page.locator('#toast').textContent(), /恢复内置示例/);
    const downloadEvent = page.waitForEvent('download');
    await page.locator('#downloadBtn').click();
    const download = await downloadEvent;
    assert.equal(download.suggestedFilename(), 'order_user_lookup.groovy');
    const exported = fs.readFileSync(await download.path(), 'utf8');
    assert.equal(exported, payload.scripts.lookup + '// custom change\n');
    await page.locator('#resetCode').click();
    assert.equal(await page.locator('#codeInput').inputValue(), payload.scripts.lookup);
    await page.locator('#logicTab').click();
    const downloadEvent2 = page.waitForEvent('download');
    await page.locator('#downloadBtn').click();
    const fullDownload = await downloadEvent2;
    assert.equal(fs.readFileSync(await fullDownload.path(), 'utf8'), payload.scripts.lookup);
    passed('UI-05 完整脚本导出与自定义保护', '编辑内容按原样下载；逻辑片段视图仍下载完整脚本；自定义代码不假执行');

    await page.locator('#quickDocs').click();
    await page.waitForSelector('#page-knowledge:not([hidden])');
    assert.equal(await page.locator('.doc-card').count(), 16);
    assert.equal(await page.locator('#faqList details').count(), 24);
    await page.locator('#knowledgeQuery').fill('RF-SRC-003');
    assert.ok(await page.locator('.doc-card').count() > 0);
    await page.locator('#docGrid [data-doc="02"]').click();
    assert.match(await page.locator('#modalBody').textContent(), /响应路径/);
    await page.locator('#modalBody [data-doc="06"]').first().click();
    assert.match(await page.locator('#modalTitle').textContent(), /错误处理/);
    await page.locator('#closeModal').click();
    await page.locator('#knowledgeQuery').fill('no_document_exists_777');
    assert.equal(await page.locator('.doc-card').count(), 0);
    assert.match(await page.locator('#docGrid').textContent(), /没有匹配文档/);
    await page.locator('#knowledgeQuery').fill('');
    await page.locator('[data-category="platform"]').click();
    assert.equal(await page.locator('.doc-card').count(), 3);
    await page.locator('#faqList summary').first().click();
    assert.equal(await page.locator('#faqList details').first().evaluate(el => el.open), true);
    await page.screenshot({ path: path.join(screenshotDir, 'knowledge-desktop.png'), fullPage: false, animations: 'disabled' });
    passed('UI-06 知识检索、分类、FAQ 与文档跳转', '16 文档、24 FAQ；错误码全文检索；文档互跳；空结果；平台分类 3 份');

    await page.locator('#tourBtn').click();
    for (let i = 0; i < 3; i++) await page.locator('#tourNext').click();
    assert.match(await page.locator('#tourTitle').textContent(), /知识可查证/);
    await page.locator('#tourNext').click();
    assert.equal(await page.locator('#tourModal').evaluate(el => el.open), false);
    await page.locator('#presentBtn').click();
    assert.equal(await page.locator('#presentBtn').getAttribute('aria-pressed'), 'true');
    assert.equal(await page.locator('#codeInput').evaluate(el => getComputedStyle(el).fontSize), '15px');
    await page.locator('#presentBtn').click();
    await page.locator('[data-route="history"]').click();
    assert.ok(await page.locator('.history-item').count() >= 7);
    await page.reload();
    assert.match(await page.locator('#historyList').textContent(), /还没有课堂运行记录/);
    assert.equal(await page.locator('#page-history').isVisible(), true);
    await page.locator('[data-route="workspace"]').click();
    await page.waitForTimeout(250);
    await page.locator('#codeInput').evaluate(el => { el.scrollTop = 220; el.dispatchEvent(new Event('scroll')); });
    assert.equal(await page.locator('#editorHighlight').evaluate(el => el.scrollTop), await page.locator('#codeInput').evaluate(el => el.scrollTop));
    await page.locator('#codeInput').evaluate(el => { el.scrollTop = 0; el.dispatchEvent(new Event('scroll')); });
    const sizes = await page.evaluate(() => Object.fromEntries(['.page-heading h1', '.code-input', '.row-note', '.result-tabs button', 'td'].map(selector => [selector, getComputedStyle(document.querySelector(selector)).fontSize])));
    const desktopOverflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    assert.equal(desktopOverflow, false);
    await page.screenshot({ path: path.join(screenshotDir, 'desktop-after-review.png'), fullPage: true, animations: 'disabled' });
    await page.locator('[data-route="overview"]').click();
    await page.waitForTimeout(250);
    await page.screenshot({ path: path.join(screenshotDir, 'overview-desktop.png'), fullPage: true, animations: 'disabled' });
    passed('UI-07 桌面讲解、导航与滚动对齐', { viewport: '1440×1080', sizes, screenshot: 'screenshots/desktop-after-review.png', history: '刷新后清空当前会话，hash 路由仍可达' });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(pathToFileURL(entry).href);
    await page.waitForTimeout(300);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.locator('#menuBtn').click();
    await page.locator('[data-route="sources"]').click();
    await page.locator('#page-sources').waitFor({ state: 'visible' });
    await page.locator('#sidebarShade').waitFor({ state: 'hidden' });
    assert.equal(await page.locator('#sidebarShade').isVisible(), false);
    await page.locator('#sourceCards [data-source="orders"]').click();
    const rect = await page.locator('#contentModal').boundingBox();
    assert.ok(rect.x >= 0 && rect.x + rect.width <= 391);
    await page.locator('#modalBody').evaluate(el => el.scrollTop = 120);
    const header = await page.locator('#contentModal .modal-head').boundingBox();
    assert.ok(header.y >= 0 && header.y + header.height <= 844);
    await page.keyboard.press('Escape');
    await page.locator('#menuBtn').click();
    await page.locator('[data-route="workspace"]').click();
    await page.locator('#fixtureSelect').selectOption('empty');
    await simulate();
    await page.locator('#fixtureSelect').selectOption('normal');
    await page.waitForTimeout(250);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: path.join(screenshotDir, 'mobile-after-review.png'), fullPage: true, animations: 'disabled' });
    passed('UI-07 移动视口与弹窗', '390×844，无页面横向溢出；导航可打开关闭；详情在视口内；移动端可运行');

    assert.deepEqual(errors, []);
    assert.deepEqual(remoteRequests, []);
    passed('全程无 JavaScript 错误或远程请求', '所有功能在 file:// 离线页面中完成');
    fs.writeFileSync(path.join(reportDir, 'browser-results.json'), JSON.stringify({ status: 'PASS', checks, errors, remoteRequests }, null, 2));
    console.log(`\n${checks.length} checks passed.`);
  } finally { await browser.close(); }
}

main().catch(error => {
  fs.writeFileSync(path.join(reportDir, 'browser-results.json'), JSON.stringify({ status: 'FAIL', checks, errors, remoteRequests, failure: error.stack }, null, 2));
  console.error(error);
  process.exitCode = 1;
});
