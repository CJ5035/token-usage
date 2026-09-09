/* T8 (delivery 2) 真实浏览器验收: 统计页 / 首页 / 统一记录页 / 关于·欢迎·页脚。
 *
 * 输入: GOUSAGE_TEST_URL 或 argv[2] = fixture 服务 URL (仅接受 http://127.0.0.1:<port>,
 * 由 scripts/serve_codex_fixture.py 打印), 不使用生产 URL。
 * 截图输出: artifacts/codex-ui/*.png
 * 交付二: 记录页统一来源筛选 (默认 source=all)/显式 codex/分页跨页不重复/
 * 会话合计与明细一致; 交付一"无来源筛选器"边界已消除。
 * 依赖: .probe/codex-ui-runtime/node_modules/playwright (任务临时安装, 非运行时依赖)。
 */

const { chromium } = require("../.probe/codex-ui-runtime/node_modules/playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");

const SHOT = "artifacts/codex-ui";

/* /api/codex/summary 固定契约 (键集与 tests/test_codex_server.py::test_codex_summary_fixed_keys 一致) */
function codexSummary(range, opts = {}) {
  const o = Object.assign({ tokens: 130, model: "codex-ui-model", dbFound: true }, opts);
  const day = (offset, tokens) => ({
    date: new Date(Date.now() - offset * 86400000).toISOString().slice(0, 10),
    total_tokens: tokens,
    request_count: tokens > 0 ? 1 : 0,
  });
  const agg = {
    request_count: 1, total_input_tokens: 100, total_output_tokens: 30,
    total_tokens: o.tokens, avg_tps: null, total_cost_usd: null, cost_usd: null,
  };
  const row = (extra) => Object.assign({}, agg, extra);
  const week = [0, 1, 2, 3, 4, 5, 6].map((i) => day(i, i === 0 ? o.tokens : 0));
  return {
    range,
    db_found: o.dbFound,
    source_found: o.dbFound,
    has_data: o.dbFound,
    request_count_exact: false,
    cost_available: false,
    cost_partial: false,
    cost_unavailable_channels: ["codex"],
    totals: row({}),
    today: row({}),
    channels: o.dbFound ? [row({ provider_id: "codex" })] : [],
    models: o.dbFound ? [row({ provider_id: "codex", model: o.model })] : [],
    daily: week,
    daily7: week,
    last_import_at: null,
    import_error: null,
    importing: false,
    revision: 0,
  };
}

/* /api/state 最小形状: checkState/pollUntilIdle/renderSyncBanner 消费的字段 */
function statePayload(loggedIn, codex) {
  return {
    logged_in: loggedIn,
    progress: { running: false },
    codex: Object.assign(
      { source_found: true, has_data: true, running: false, revision: 0, last_import_at: null, error: null },
      codex),
  };
}

(async () => {
  const url = process.env.GOUSAGE_TEST_URL || process.argv[2];
  assert.ok(url && /^http:\/\/127\.0\.0\.1:\d+$/.test(url), "fixture URL required");
  fs.mkdirSync(SHOT, { recursive: true });
  const browser = await chromium.launch();
  const passes = [];
  const ok = (name) => { passes.push(name); console.log("PASS", name); };
  const watchErrors = (page) => {
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    return errors;
  };

  try {
    /* ===== 1. 基础断言: 3 视口 × 统计页/记录页/首页 (真实 fixture 服务) ===== */
    for (const size of [{ width: 1440, height: 900 }, { width: 860, height: 600 },
                        { width: 390, height: 844 }]) {
      const page = await browser.newPage({ viewport: size });
      const errors = watchErrors(page);
      await page.goto(url);
      await page.locator("#login-overlay").waitFor({ state: "hidden" });
      ok(`overlay hidden @${size.width}`);
      await page.locator('[data-page="stats"]').click();
      await page.locator("#codex-model-body").getByText("codex-ui-model").waitFor();
      ok(`stats model row @${size.width}`);
      const kpis = await page.locator("#codex-kpis").innerText();
      assert.match(kpis, /130/);
      assert.doesNotMatch(kpis, /NaN|undefined/);
      ok(`stats kpis 130, no NaN/undefined @${size.width}`);
      // 内部滚动容器: fullPage 抓不到折叠下方区块, 截图前把 Codex 区块滚入视口
      await page.locator("#codex-stats").scrollIntoViewIfNeeded();
      await page.locator("#codex-stats").screenshot({ path: `${SHOT}/stats-codex-${size.width}.png` });
      ok(`stats codex block screenshot @${size.width}`);
      await page.locator('[data-page="records"]').click();
      // 交付二: 统一来源记录页 — 默认"全部"并显式发送 source=all (需求 §5.3),
      // 七个来源选项; fixture 无远程账号时仅含 Codex 种子记录, 无 NaN/undefined
      assert.equal(await page.locator("#rec-source-filter").count(), 1);
      await page.locator("#records-body").getByText("codex-ui-model").first().waitFor();
      assert.equal(await page.locator("#rec-source-filter option").count(), 7);
      assert.equal(await page.locator("#rec-source-filter").inputValue(), "all");
      assert.doesNotMatch(await page.locator("#records-body").innerText(), /NaN|undefined/);
      ok(`records unified source filter (default all, codex visible) @${size.width}`);
      if (size.width === 390) {
        // 窄视口: 会话/记录两表在 .usage-scroll 容器内横向滚动可用 (内容超宽且能滚到末端)
        for (const wrap of await page.locator(".usage-scroll").all()) {
          const scroll = await wrap.evaluate((el) => {
            el.scrollLeft = el.scrollWidth;
            return { overflowX: getComputedStyle(el).overflowX,
                     scrollable: el.scrollWidth > el.clientWidth };
          });
          assert.ok(["auto", "scroll"].includes(scroll.overflowX) && scroll.scrollable,
            "usage-scroll scrolls horizontally");
          assert.ok(await wrap.evaluate((el) => el.scrollLeft > 0), "scrolled to end");
        }
        ok("records narrow viewport: both tables scroll inside container @390");
      }
      await page.locator("#page-records .card.records").scrollIntoViewIfNeeded();
      await page.locator("#page-records").screenshot({ path: `${SHOT}/records-${size.width}.png` });
      ok(`records page screenshot @${size.width}`);
      await page.locator('[data-page="home"]').click();
      const codexTab = page.locator('#channel-tabs [data-ch="codex"]');
      await codexTab.waitFor();
      await codexTab.click();
      assert.equal(await page.locator("#zcode-quota").isVisible(), false);
      ok(`home codex tab, zcode-quota hidden @${size.width}`);
      await page.screenshot({ path: `${SHOT}/home-${size.width}.png`, fullPage: true });
      assert.deepEqual(errors, []);
      ok(`no pageerror @${size.width}`);
      await page.close();
    }

    /* ===== 2. 统计页 range today/all + 画布/图标渲染门禁 (zh/light 默认) ===== */
    {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      const errors = watchErrors(page);
      await page.goto(url);
      await page.locator("#login-overlay").waitFor({ state: "hidden" });
      await page.locator('[data-page="stats"]').click();
      await page.locator("#codex-model-body").getByText("codex-ui-model").waitFor();
      await page.locator('#stats-pills .pill[data-r="today"]').click();
      await page.locator("#codex-kpis").getByText("130").first().waitFor();
      ok("stats range today: totals 130");
      await page.locator('#stats-pills .pill[data-r="all"]').click();
      await page.locator("#codex-kpis").getByText("130").first().waitFor();
      assert.doesNotMatch(await page.locator("#codex-kpis").innerText(), /NaN|undefined/);
      ok("stats range all: totals 130");
      await page.locator("#codex-trend-empty").waitFor({ state: "hidden" });
      // 渲染门禁: Chart.js 首帧动画帧后才非空, 轮询等待非空像素出现 (非数据断言)
      await page.waitForFunction(() => {
        const c = document.getElementById("codex-trend-chart");
        if (!c) return false;
        const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
        for (let i = 3; i < d.length; i += 4) if (d[i] !== 0) return true;
        return false;
      }, { timeout: 5000 });
      const pixels = await page.evaluate(() => {
        const c = document.getElementById("codex-trend-chart");
        const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
        let n = 0;
        for (let i = 3; i < d.length; i += 4) if (d[i] !== 0) n++;
        return n;
      });
      ok(`codex trend canvas non-empty pixels=${pixels} (render gate)`);
      const icon = page.locator("#codex-model-body img").first();
      await icon.waitFor();
      assert.ok(await icon.evaluate((el) => el.naturalWidth > 0), "model icon asset loaded");
      ok("model icon asset loaded (naturalWidth>0)");
      assert.deepEqual(errors, []);
      await page.locator("#codex-stats").scrollIntoViewIfNeeded();
      await page.locator("#codex-stats").screenshot({ path: `${SHOT}/stats-zh-light-1440.png` });
      await page.close();
    }

    /* ===== 3. zh/en × 亮/暗主题各一轮 ===== */
    {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      const errors = watchErrors(page);
      await page.goto(url);
      await page.locator("#login-overlay").waitFor({ state: "hidden" });
      assert.match(await page.locator("#tb-theme").innerText(), /暗色/);
      ok("zh light: default, theme button shows 暗色");
      await page.locator("#tb-theme").click();
      assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), "dark");
      assert.match(await page.locator("#tb-theme").innerText(), /亮色/);
      await page.locator('[data-page="stats"]').click();
      await page.locator("#codex-model-body").getByText("codex-ui-model").waitFor();
      await page.locator("#codex-stats").scrollIntoViewIfNeeded();
      await page.locator("#codex-stats").screenshot({ path: `${SHOT}/stats-zh-dark.png` });
      ok("zh dark: theme attr + button text, stats rendered");
      await page.locator('[data-page="settings"]').click();
      await page.locator('#set-lang-pills .pill[data-v="en"]').click();
      assert.match(await page.locator("#tb-theme").innerText(), /Light/);
      ok("en applied (theme button shows Light)");
      await page.locator('[data-page="stats"]').click();
      await page.locator("#codex-model-body").getByText("codex-ui-model").waitFor();
      await page.locator("#codex-stats").scrollIntoViewIfNeeded();
      await page.locator("#codex-stats").screenshot({ path: `${SHOT}/stats-en-dark.png` });
      ok("en dark: stats rendered");
      await page.locator('[data-page="settings"]').click();
      await page.locator('#set-theme-pills .pill[data-v="light"]').click();
      assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), "light");
      ok("en light applied via settings pills");
      await page.locator('[data-page="stats"]').click();
      await page.locator("#codex-model-body").getByText("codex-ui-model").waitFor();
      await page.locator("#codex-stats").scrollIntoViewIfNeeded();
      await page.locator("#codex-stats").screenshot({ path: `${SHOT}/stats-en-light.png` });
      ok("en light: stats rendered");
      assert.deepEqual(errors, []);
      await page.close();
    }

    /* ===== 4. 首页 cost/tokens 切换 (Codex 无费用 → 明确不可用提示, 不显示 0) ===== */
    {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      const errors = watchErrors(page);
      await page.goto(url);
      await page.locator("#login-overlay").waitFor({ state: "hidden" });
      await page.locator('#report-metric button[data-m="cost"]').click();
      await page.locator("#report-cost-hint").waitFor({ state: "visible" });
      ok("home metric=cost: cost-unavailable hint visible (codex cost NULL)");
      await page.screenshot({ path: `${SHOT}/home-cost.png`, fullPage: true });
      await page.locator('#report-metric button[data-m="tokens"]').click();
      await page.locator("#report-cost-hint").waitFor({ state: "hidden" });
      ok("home metric=tokens: hint hidden");
      await page.screenshot({ path: `${SHOT}/home-tokens.png`, fullPage: true });
      assert.deepEqual(errors, []);
      await page.close();
    }

    /* ===== 5. 空源零数据 (route 拦截: summary db_found=false) ===== */
    {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      const errors = watchErrors(page);
      await page.route("**/api/state", (route) => route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(statePayload(true, { source_found: false, has_data: false })),
      }));
      await page.route("**/api/codex/summary*", (route) => route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(codexSummary("all", { dbFound: false })),
      }));
      await page.goto(url);
      await page.locator("#login-overlay").waitFor({ state: "hidden" });
      await page.locator('[data-page="stats"]').click();
      await page.locator("#codex-missing").waitFor({ state: "visible" });
      assert.equal(await page.locator("#codex-kpis").isVisible(), false);
      assert.equal(await page.locator("#codex-model-body").isVisible(), false);
      ok("empty source: missing copy visible, KPI/tables hidden");
      await page.locator("#codex-missing").scrollIntoViewIfNeeded();
      await page.screenshot({ path: `${SHOT}/stats-empty.png` });
      assert.deepEqual(errors, []);
      await page.close();
    }

    /* ===== 6. range 响应乱序: 慢的 7d(111) 必须被丢弃, 保持 all(222) ===== */
    {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      const errors = watchErrors(page);
      await page.route("**/api/codex/summary*", async (route) => {
        const range = new URL(route.request().url()).searchParams.get("range") || "7d";
        const payload = range === "7d"
          ? codexSummary("7d", { tokens: 111, model: "m-7d" })
          : codexSummary("all", { tokens: 222, model: "m-all" });
        if (range === "7d") await new Promise((r) => setTimeout(r, 1500));
        await route.fulfill({ contentType: "application/json", body: JSON.stringify(payload) });
      });
      await page.goto(url);
      await page.locator("#login-overlay").waitFor({ state: "hidden" });
      await page.locator('[data-page="stats"]').click();
      await page.locator('#stats-pills .pill[data-r="all"]').click();
      await page.locator("#codex-model-body").getByText("m-all").waitFor();
      assert.match(await page.locator("#codex-kpis").innerText(), /222/);
      await page.waitForTimeout(2000);   // 让迟到的 7d 响应到达
      assert.match(await page.locator("#codex-kpis").innerText(), /222/);
      assert.doesNotMatch(await page.locator("#codex-kpis").innerText(), /111/);
      assert.match(await page.locator("#codex-model-body").innerText(), /m-all/);
      ok("out-of-order: stale 7d(111) discarded, all(222) kept");
      await page.locator("#codex-stats").scrollIntoViewIfNeeded();
      await page.locator("#codex-stats").screenshot({ path: `${SHOT}/stats-ooo-1440.png` });
      assert.deepEqual(errors, []);
      await page.close();
    }

    /* ===== 7. 首次 importing → 完成自动刷新 (route 拦截 /api/state 次数) ===== */
    {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      const errors = watchErrors(page);
      let stateCalls = 0;
      await page.route("**/api/state", (route) => {
        stateCalls += 1;
        // 调用1=checkState, 调用2=第1个轮询 tick (指示条可见), 调用3 起 importing 完成
        const running = stateCalls <= 2;
        route.fulfill({
          contentType: "application/json",
          body: JSON.stringify(statePayload(false, { running, revision: 1 })),
        });
      });
      await page.goto(url);
      await page.locator("#login-overlay").waitFor({ state: "hidden" });
      await page.locator("#sync-indicator").waitFor({ state: "visible", timeout: 10000 });
      ok("first import: sync indicator visible while codex.running");
      await page.locator("#sync-indicator").waitFor({ state: "hidden", timeout: 15000 });
      ok("import done: sync indicator hidden");
      await page.locator("#report-range-kpis").waitFor();
      assert.ok((await page.locator("#report-range-kpis").innerText()).trim().length > 0,
        "dashboard refreshed after import idle");
      ok("auto-refresh after idle: report KPIs rendered");
      assert.deepEqual(errors, []);
      await page.screenshot({ path: `${SHOT}/home-import-done.png`, fullPage: true });
      await page.close();
    }

    /* ===== 8. 关于/页脚 + 欢迎页 (本地访问入口文案, 空 state 拦截出欢迎页) ===== */
    {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      await page.goto(url);
      await page.locator("#login-overlay").waitFor({ state: "hidden" });
      await page.locator('[data-page="about"]').click();
      const aboutText = await page.locator("#page-about").innerText();
      assert.match(aboutText, /Codex/);
      assert.match(await page.locator("#page-about .pagefoot").innerText(), /Codex/);
      ok("about + footer copy mention Codex");
      await page.screenshot({ path: `${SHOT}/about.png`, fullPage: true });
      await page.close();

      const p2 = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      await p2.route("**/api/state", (route) => route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(statePayload(false, { source_found: false, has_data: false })),
      }));
      await p2.goto(url);
      await p2.locator("#login-overlay").waitFor({ state: "visible" });
      assert.match(await p2.locator("#login-overlay").innerText(), /Codex/);
      ok("welcome overlay (no login, no local codex) mentions Codex");
      await p2.screenshot({ path: `${SHOT}/welcome.png`, fullPage: true });
      await p2.close();
    }

    /* ===== 9. 统一记录: 显式 codex 筛选 / source=all 分页跨页不重复 / 会话勾稽 / zh-en × 亮暗 ===== */
    {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      const errors = watchErrors(page);
      await page.goto(url);
      await page.locator("#login-overlay").waitFor({ state: "hidden" });
      await page.locator('[data-page="records"]').click();
      // 默认"全部" (显式 source=all): fixture 无远程账号时仅含 Codex 种子记录 (10 条)
      await page.locator("#records-body").getByText("codex-ui-model").first().waitFor();
      // 显式 codex: 统一明细可见模型与 130 total, 来源列显示 Codex
      let recs = page.waitForResponse((r) => r.url().includes("/api/usage/records")
        && r.url().includes("source=codex"));
      await page.locator("#rec-source-filter").selectOption("codex");
      await recs;
      const firstRow = await page.locator("#records-body tr").first().innerText();
      assert.match(firstRow, /Codex/);
      assert.match(firstRow, /codex-ui-model/);
      assert.match(firstRow, /130/);
      assert.doesNotMatch(await page.locator("#records-body").innerText(), /NaN|undefined/);
      ok("records source=codex: first row Codex/codex-ui-model/130, no NaN|undefined");
      // source=all 分页: 第 1/2 页 source_record_id 不重复 (API 集合 + UI 行文本双重核对)
      recs = page.waitForResponse((r) => r.url().includes("/api/usage/records")
        && r.url().includes("source=all"));
      await page.locator("#rec-source-filter").selectOption("all");
      const allData = await (await recs).json();
      assert.equal(allData.total, 10);
      const page1Rows = (await page.locator("#records-body tr").allInnerTexts())
        .filter((t) => t.trim());
      const p2Resp = page.waitForResponse((r) => r.url().includes("/api/usage/records")
        && r.url().includes("page=2"));
      await page.locator("#pg-next").click();
      const page2Data = await (await p2Resp).json();
      assert.equal(new Set([...allData.records, ...page2Data.records]
        .map((r) => r.source_record_id)).size, allData.total);
      // 等第 2 页渲染完成 (至少一行文本不同于第 1 页集合)
      await page.waitForFunction(
        (prev) => [...document.querySelectorAll("#records-body tr")]
          .map((tr) => tr.innerText.trim()).filter(Boolean)
          .some((r) => !prev.includes(r)),
        page1Rows, { timeout: 5000 });
      const page2Rows = (await page.locator("#records-body tr").allInnerTexts())
        .filter((t) => t.trim());
      assert.equal(page2Rows.length, 3);
      assert.ok(page2Rows.every((r) => !page1Rows.includes(r)), "page 2 rows differ from page 1");
      ok("records source=all paging: 10 total, page1/page2 rows disjoint");
      // 会话用量: 同 source 下 codex 会话合计与明细一致 (ui 会话 10 条, total=全部页明细合计)
      const sesApi = await (await page.request.get(
        `${url}/api/usage/sessions?source=all&page=1&page_size=7`)).json();
      assert.equal(sesApi.total, 1);
      assert.equal(sesApi.records[0].session_id, "ui");
      assert.equal(sesApi.records[0].request_count, 10);
      const recSum = [...allData.records, ...page2Data.records]
        .reduce((n, r) => n + r.total_tokens, 0);
      assert.equal(sesApi.records[0].total_tokens, recSum);
      const sessionsText = await page.locator("#sessions-body").innerText();
      assert.match(sessionsText, /codex-ui-model|ui/);
      assert.match(sessionsText, new RegExp(`\\b${recSum}\\b`));
      ok(`records sessions: ui session total ${recSum} == records sum (source=all)`);
      await page.locator("#page-records").screenshot({ path: `${SHOT}/records-paging-1440.png` });
      // zh/en × 亮/暗各过一轮记录页 (zh/light 已随循环截图, 此处补 dark/en)
      await page.locator("#tb-theme").click();
      assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), "dark");
      await page.locator("#page-records").screenshot({ path: `${SHOT}/records-zh-dark-1440.png` });
      await page.locator('[data-page="settings"]').click();
      await page.locator('#set-lang-pills .pill[data-v="en"]').click();
      assert.match(await page.locator("#tb-theme").innerText(), /Light/);
      await page.locator('[data-page="records"]').click();
      await page.locator("#records-body").getByText("codex-ui-model").first().waitFor();
      await page.locator("#page-records").screenshot({ path: `${SHOT}/records-en-dark-1440.png` });
      await page.locator('[data-page="settings"]').click();
      await page.locator('#set-theme-pills .pill[data-v="light"]').click();
      assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), "light");
      await page.locator('[data-page="records"]').click();
      await page.locator("#records-body").getByText("codex-ui-model").first().waitFor();
      assert.equal(await page.locator("#rec-source-filter").inputValue(), "all");
      await page.locator("#page-records").screenshot({ path: `${SHOT}/records-en-light-1440.png` });
      ok("records zh/en x light/dark rounds done, source selection kept");
      assert.deepEqual(errors, []);
      await page.close();
    }
  } finally {
    await browser.close();
  }
  console.log(`RESULT pass=${passes.length} fail=0`);
})().catch((error) => { console.error(error); process.exitCode = 1; });
