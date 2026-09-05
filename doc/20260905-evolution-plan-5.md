# 实施计划 EVOLUTION-5：首页 all 页签加载/切档位 0~3.5s 无反馈空窗【v6 终稿】

- **日期**：2026-09-05（v6 终稿：门禁2 第 5 轮架构师 3 条单句级阻塞按其明确改法落入正文）
- **门禁2 状态**：达 5 轮上限，最终 2/3 席通过（PM/UX 官）；架构师 3 条阻塞均为"修订记录声称已做、正文零落点"的文档自洽问题，其明确改法已全部落入本 v6 正文（见修订记录 v6），实施后按测试点人工复核
- **依据**：`doc/evolution-diagnosis-5.md` v3.1 相关结论（门禁1 三轮 3/3 通过）+ 评委建议
- **等级**：P2（6/10，接近 P1 线）
- **改动范围**：5 文件——`app/dsh_api.py`（后台化）、`app/server.py`（端点降级）、`app/main.py`（预热+import）、`app/db.py`（两索引）、`app/web/app.js`（all 分支 + loadDshUsage）；后端两项建议合并为一次提交一次复测；前端项可先行

## 改动清单

### 1. dsh 过期后台化（app/dsh_api.py，收益最大：3.5s→0）

`get_dsh_usage()` 对齐 `_ensure_quota_async` 惰性模式（server.py:237-267，本项目第三次复用）：

```python
_refreshing = False          # 防重入标志（对齐 server.py:249-254 _quota_refreshing 模式）
_fail_count = 0              # 连续失败计数
_FAIL_BACKOFF_SECONDS = 60.0 # 失败退避窗（区别于正常 TTL 15s）
_last_fail_ts = 0.0          # 最近一次失败时刻（退避判定基准）

def get_dsh_usage():
    global _cache_payload, _cache_ts, _refreshing, _fail_count
    now = time.time()
    if _cache_payload is not None and now - _cache_ts < CACHE_TTL_SECONDS:
        return _cache_payload
    # 后台刷新守卫: 防重入 + 连续失败 >=3 次停止自动重试（降级路径见下）+ 失败退避 60s 内不再 spawn
    if not _refreshing and _fail_count < 3 and now - _last_fail_ts >= _FAIL_BACKOFF_SECONDS:
        _refreshing = True
        threading.Thread(target=_rescan_worker, daemon=True, name="gousage-dsh-rescan").start()
    return _cache_payload if _cache_payload is not None else _empty_result()  # 冷启动空态, found=false 天然兼容

def degraded():                  # 降级判定: 模块自持, server 层经此判定, 勿直接读 _fail_count 私有变量
    return _fail_count >= 3

def _rescan_worker():
    global _cache_payload, _cache_ts, _refreshing, _fail_count, _last_fail_ts
    try:
        payload = scan()
        _cache_payload, _cache_ts, _fail_count = payload, time.time(), 0
        _last_fail_ts = 0.0           # 退出退避窗（_fail_count=0 已放行, 此举语义更完整）
        print(f"[dsh] rescan ok: {payload.get('sessions_count')} sessions", flush=True)  # stale 仅日志, 不改响应 schema
    except Exception:
        _fail_count += 1
        _last_fail_ts = time.time()   # 60s 退避真实生效（对齐 _ensure_quota_async "失败也写缓存
                                      # 防前端无限刷新"意图, server.py:260-261）
        if _cache_payload is None:    # 仅冷启动失败写空态（消解 payload=None 时 TTL 短路永不命中的
            _cache_payload = _empty_result()  #   退避漏洞）; 热态失败【保留 stale 真数据】——
                                              #   禁止用空态覆盖已持真数据, 否则"连续失败期间持续返回
                                              #   stale"验收必失败且首页 dsh 行用户可见消失
    finally:
        _refreshing = False
```

- **冷启动语义**：进程首次返回 `_empty_result()`（server 层 `dsh_found` 分支天然兼容 found=false，首屏零阻塞）+ **启动预热**（main.py 在 `zcode_quota_warmup()` 调用点旁追加 `dsh_api.get_dsh_usage()` 触发一次后台扫描；**main.py 现未 import dsh_api，落地时补 `from . import dsh_api`**）；
- **"自愈"如实表述**：预热完成后服务端缓存就绪，**下一次交互（切档位/切页签）即得真数据**（首页无自动轮询，不做广播）；
- **降级路径（v2 据实重写）**：触发点 = **切至统计页**（app.js:478 → `loadDshUsage()`，是 `/api/dsh/usage` 的唯一前端调用；不存在"手动刷新"入口）。server 层经 **`dsh_api.degraded()`**（模块内判 `_fail_count >= 3`，不跨模块读私有变量）为真时调模块暴露的 `scan_sync()`（同步扫描）；配套 **§3 追加 loadDshUsage 最小改动**（见 §3b）——降级扫描期间 `#dsh-stats` 有加载反馈、失败 toast 且不清空旧内容；**首页 windows/channels/channel-overview 三端点在连续失败期间持续返回 stale（不降级）属预期行为**，勿在验收时判为缺陷；5s 静默重试（app.js:628，quiet=true）不触发降级，仍拿 stale；
- **不加"数据可能非最新"提示**（显式决策：最大陈旧 ~18s 对分钟粒度面板不可感知）；
- 线程安全：`_cache_payload` 引用替换在 GIL 下原子（server.py:1287 注释已明令消费方只读）；`_refreshing` 的 check-then-set 存在 TOCTOU 窗口（GIL 下最坏并发双扫描、无死锁），**与 `_quota_refreshing` set 模式风险同级，接受该口径**（严格化可加 threading.Lock，非必需）。

### 2. zcode/cc 两表表达式索引（app/db.py，迁移区）

`_init_schema` 迁移区（db.py:305-310 旁，对齐 idx_usage_*_utc 模式）：

```python
con.execute("CREATE INDEX IF NOT EXISTS idx_zcode_utc ON zcode_usage(datetime(started_at))")
con.execute("CREATE INDEX IF NOT EXISTS idx_cc_utc ON claudecode_usage(datetime(started_at))")
```

- `datetime(started_at)` 单参为确定性函数，可入索引（substr+localtime 已被 db.py:300-302 注释记载否决）；
- 消费方谓词（db.py:2194/2201/2299/2309/2329 的 `datetime(z.started_at) >= datetime(?)`）已与索引表达式逐字匹配，**自动命中零改动**；
- 存量库一次性建索引开销（本机 145MB/415 文件量级为秒级）写入验收说明；新装库随迁移自动创建。

### 3. all 分支 loading + 守卫 + 三波并一波（app/web/app.js:2119-2146）

对齐单渠道模式（app.js:540-548）：

```js
let allSeq = 0;                                    // 与单渠道 chSeq 独立（各自独立 seq 最小方案;
                                                   // #report-all/#report-single 独立容器, 切换必重发,
                                                   // 级联失效仅在实测乱序覆盖时再加）
async function loadReportAll(quiet = false) {
  const seq = ++allSeq;
  const box = $("report-all");
  box.classList.add("swapping");                   // 旧内容不清空（隐式 SWR, 禁止再设计独立 SWR 缓存）
  try {
    const range = state.range;                         // 局部快照（含 metric, 见下）防在途 state 漂移
    const metric = state.reportMetric;
    const [w, rows, ov, zq, daily, hourly] = await Promise.all([   // 三波并一波
      api(`/api/report/windows`),
      api(`/api/report/channels?range=${range}`),
      api(`/api/accounts/overview`),
      api(`/api/zcode/quota`).catch(() => null),
      api(`/api/report/daily?range=${range}&metric=${metric}`),
      (range === "today" || range === "yesterday")  // 档位条件保留（条件性 promise）
        ? api(`/api/report/hourly?date=${range}`)
        : Promise.resolve(null),
    ]);
    if (seq !== allSeq) return;                    // 过期响应丢弃（缓存写入在守卫后, 最新胜出）
                                                   // 注意: hourly 卡 closest(".card").hidden 切换与
                                                   // 标题 data-i18n 更新属渲染副作用, 必须在本守卫之后执行
    ...原渲染逻辑...
    reportDailyCache = { range, metric, data: daily };   // EVOLUTION-4 缓存写入点（键用局部快照, 勿回读全局）
    reportHourlyCache = hourly ? { range, data: hourly } : null;
    box.classList.remove("swapping");
  } catch (e) {
    if (seq === allSeq) {                                  // 错误路径必须回收加载态;
      box.classList.remove("swapping");                    // toast 同样纳入 seq 守卫（防被取代的旧请求
      if (!quiet) toast(t("loadFailed") + ": " + e);       // 迟到失败时对已显示新数据的界面报错）
    }
  }
}
```

- **SWR 等价声明**：swapping 不清空旧 DOM，补 loading+守卫即隐式达成 stale-while-revalidate，禁止独立 SWR 缓存；
- **quiet 5s 静默重试的减淡脉冲：接受为已知行为**（app.js:628 配额失败时每 5s 调 loadDashboard(true) → 本分支加 swapping，与单渠道分支同策略；dsh 后台化后热态 ~92ms、opacity 过渡 .15s 基本不可见；仅重扫窗口期 GIL 拖慢时可能数秒变暗，概率低且有真实刷新对应，不算假状态）；`#report-metric` 指标 seg 位于 #report-all 容器内（index.html:67-70），减淡时与面板同容器一并变暗，属同一已知行为；
- 守卫序号 `allSeq` 与单渠道 `chSeq` 独立（最小方案）；
- hourly 并入消除 today 档两段式弹入。

### 3b. loadDshUsage 最小改动（app.js:946-956，降级路径的用户感知载体）

```js
async function loadDshUsage() {
  const box = $("dsh-stats");
  if (!box) return;                                    // 存活防御, 必须保留（app.js:948 现状）
  box.classList.add("swapping");                       // 请求前加载态（复用 .swapping）
  try {
    const d = await api("/api/dsh/usage");
    dshUsageLast = d;                                  // 存活赋值, 必须保留（app.js:951 现状）——
                                                       //   语言切换重渲（app.js:360）与 #dsh-dim 档位
                                                       //   seg 重渲（app.js:1958）的唯一数据源, 丢失则
                                                       //   两处"点了没反应"/半翻译卡片
    // 页面可见性守卫可选: 渲染进已隐藏容器无副作用, 再次进入会重拉;
    // 如保留则用 state.page !== "stats"（勿用不存在的 pageVisible——照抄抛 ReferenceError
    // 会进 catch 触发 toast, 击穿本节体验承诺）, 且只包住 renderDsh、不跳过 remove("swapping")
    renderDsh(d);
    box.classList.remove("swapping");
  } catch (e) {
    box.classList.remove("swapping");
    // 注意: 不再置 dshUsageLast = null（现状 app.js:954 的置 null 是配合旧 box.hidden 隐藏
    //   语义; 新语义"失败保留旧内容 + toast"下置 null 会使保留的旧 DOM 与缓存脱钩,
    //   语言切换后新旧语言混杂）
    toast(t("loadFailed") + ": " + e);                 // 失败 toast 且**不清空/隐藏旧内容**
  }
}
```

现状 catch 为 `box.hidden = true` 静默隐藏整块（无 toast）——改为保留旧内容 + toast；**loadDshUsage 不加序号守卫：降级同步扫描期间离开再回会并发两个 scan_sync，后到胜出（dshUsageLast 覆盖 + renderDsh 全量重渲，幂等无错乱），接受为已知口径**；**app.js:940-944 函数头注释（"fetch 异常 → 整块隐藏"）须同步更新为新语义**，防后续维护者按注释修回静默隐藏；若本就无旧内容（冷启动失败）则维持 hidden 兜底。**加载反馈前置条件：`#dsh-stats` 初始 hidden，仅当存在旧内容时 swapping 有视觉载体**（冷启动即降级的极端场景零反馈、失败有 toast 兜底，可接受；如愿加一行无旧内容时先 `box.hidden = false` 再 swapping 亦可，不强求）。**合并基线说明**：EVOLUTION-4 与本计划都重构 `loadReportAll`，实施顺序为 **plan-4 先落地（P1 先行）→ 本计划在其上叠加**（allSeq/swapping 先行合入不被后端复测阻塞）；`reportDailyCache`/`reportHourlyCache` 两变量由 plan-4 以 `let` 声明，本计划 §3 伪码中的写入行在 plan-4 落地后即有读取方（若实施时 plan-4 未落地，则删除这两行写入、缓存交互随 plan-4 补齐）；**谁后落地谁负责对齐**两份计划的行号。

### 4. 不做（最小化）

- windows 响应 TTL 缓存（dsh 后台化后热态仅 92ms，缓存 ROI 为负）；
- 独立 SWR 缓存、all↔单渠道级联失效（同上）；
- 子进程扫描（重扫窗口期 GIL 残留若复测超标的阶段3 备选，本方案不含）。

## 回滚方案

触及 5 文件（`app/dsh_api.py`、`app/server.py` 端点降级、`app/main.py` 预热+import、`app/db.py`、`app/web/app.js`）：**dsh_api.py / server.py / main.py 三者须原子回滚**（通过 `degraded()`/`scan_sync()` 强耦合，单独还原 dsh_api.py 会使 /api/dsh/usage 端点 AttributeError）；db.py 两条索引为 `IF NOT EXISTS` 增量（回滚不删索引，无副作用）；app.js 独立可回滚（还原 all 分支即回三波瀑布、还原 loadDshUsage 即回静默隐藏行为）。

## 修订记录

- **v6 终稿（2026-09-05，门禁2 第 5 轮架构师 3 阻塞按其明确改法落入正文）**：① scan_sync 失败语义入正文+测试点（异常透传/不写缓存/计数保留）；② degraded() 入正文与伪码（server 层经 degraded() 判定，回滚表述同步）；③ §3b 无守卫并发接受口径入正文；附 2b 编号重排、_last_fail_ts 成功复位、测试点补锚点提示（走查以 `[dsh] rescan ok` 日志为预热完成锚）。**门禁2 结论：5 轮上限，最终 2/3 席通过；架构师确认"三条阻塞均为单句级文档修订、无设计返工，补齐后无保留意见"。**
- **v5（2026-09-05，门禁2 第 4 轮 3/3 通过后文档级精确化）**：scan_sync() 失败语义补定义（异常透传/前端 catch/不清缓存）+ degraded() 耦合收紧（不跨模块读私有 _fail_count）+ §3b 无守卫并发接受口径；头部改动范围补全 5 文件；app.js:940-944 函数头旧注释同步更新要求；测试点"all 分支冷启动首载"注解按代码事实改写（#report-all 非空容器、swapping 作用于壳层、加载态可见）；已知行为扩为四条（新增"全有全无"错误语义声明）。
- **v4（2026-09-05，门禁2 第 3 轮架构师/PM 驳回后修订）**：退避机制真落地（伪码补 _FAIL_BACKOFF_SECONDS/_last_fail_ts 定义与 spawn 守卫使用点——v3 只做了文案常量化，机制仍是 15s TTL，矛盾换形态残留）；`_rescan_worker` 失败分支改为**仅冷启动（payload=None）写 _empty_result、热态保留 stale 真数据**（v3 无条件写空态会覆盖热态真数据，与降级承诺/验收说明②直接矛盾）；§3b 伪码恢复三行存活代码（`if (!box) return` 防御、try 内 `dshUsageLast = d` 赋值——语言切换/档位 seg 重渲的唯一数据源、catch 不再置 null 的取舍写明）；scan_sync() 语义定义（成功复位+写缓存）；测试点 1 拆四条可执行断言 + 降级走查补两步 + all 分支冷启动空容器前置条件。
- **v3（2026-09-05，门禁2 第 2 轮 3/3 通过后吸收建议）**：伪码补 `_fail_count < 3` 守卫（缺它则持续失败每 TTL 重扫循环）与失败写 `_empty_result()`（消解退避冷启动漏洞：payload=None 时 TTL 短路永不命中）；退避常量化 `_FAIL_BACKOFF_SECONDS=60.0`（消解 v2 "60s" 与 CACHE_TTL_SECONDS=15 的矛盾）；回滚方案 5 文件如实化（dsh_api/server/main 原子回滚）；§3 缓存键用局部快照 metric；§3b 清除 pageVisible 悬空引用（改 state.page 说明）；降级反馈前置条件与指标 seg 已知行为补写；main.py 补 import 提示；测试点同步。
- **v2（2026-09-05，门禁2 第 1 轮架构师/PM 驳回后修订）**：见 votes-5-plan.md。

## 测试验证点

1. **新增 pytest**（tests/test_dsh_background.py）：
   - TTL 过期返回 stale 且触发后台刷新（**线程同步策略**：monkeypatch `threading.Thread` 为同步执行捕获 target，或轮询 `_refreshing == False`，避免断言时序不稳定）；
   - 防重入：并发调用仅启动一次扫描；
   - 冷启动返回 `found: false` 空态不抛错；
   - 连续失败 3 次后 `scan_sync()` 降级入口可用；`scan_sync()` 成功复位 `_fail_count=0` 并写缓存；
   - 失败退避：`_rescan_worker` 失败后记 `_last_fail_ts`，60s（_FAIL_BACKOFF_SECONDS）内 get_dsh_usage 不再 spawn；
   - **热态失败保留 stale**：已有 found=true 缓存时扫描失败 → 缓存不被 `_empty_result` 覆盖（三端点持续返回 stale 的验收前提）；
   - 冷启动失败：payload=None 时失败 → 写 `_empty_result()`（found=false），TTL/退避双节流生效；
   - **scan_sync 失败语义**：模拟 scan_sync 抛错 → 缓存 payload 与 `_fail_count` 均不变（不写缓存不置零）；

2. **索引测试**（并入 test_db_multiuser 或新建）：迁移后 `EXPLAIN QUERY PLAN` 断言 zcode/cc 段 `USING INDEX idx_zcode_utc/idx_cc_utc`（**用 `db._report_range_sql` 生成真实 SQL**，防手写测试 SQL 与生产谓词漂移）；
3. 人工/截图走查：
   - dsh TTL 过期后首页 all 刷新无 3.5s 空窗（stale 即返）；
   - 并发链全链 < 500ms；后台重扫进行中窗口期复测（GIL 残留兜底口径）；
   - all 分支加载态出现/回收（含模拟失败后恢复透明度并保留旧内容）；
   - 快速连点 4 档位、all↔单渠道往返、档位×指标双维切换（入口 app.js:1940/2105），终态与最后一次点击一致；
   - today 档内容单次成块出现（无两段式弹入）；
   - 冷启动预热完成后切档位可见 dsh 数据到达（走查以伪码承诺的 `[dsh] rescan ok` 日志行为预热完成锚点，防误判时机）；
   - 单渠道分支行为不回归（chSeq/swapping 语义）；
   - **降级路径人工走查**：模拟 `_fail_count >= 3` 后进统计页 → `#dsh-stats` 出现加载态、成功刷新；失败时 toast 且旧内容保留；**追加两步**：切语言后 DSH 卡表头随语言更新（dshUsageLast 链）、`#dsh-dim` 档位 seg 切换后表格重渲；
   - all 分支冷启动首载：`#report-all` 解除 hidden 后**非空容器**（含 windows-bar 壳层/各渠道配额标题/指标 seg/双图卡标题+空 canvas/hourly 卡/明细表头，index.html:67-77；app.js:522 在 loadReportAll 之前已解除 hidden）——swapping 减淡作用于这些可见壳层，**加载态可见**；数据区短暂空壳属已知行为，勿误判为空窗缺陷；
   - **已知行为验收说明（四条）**：① 冷启动预热窗口（约 3s+）内首页 all 页签 dsh 行缺失/`channel_count` 偏少、统计页 DSH 卡显示"未检测到 DSH 本地数据"文案（数据实际存在仅未扫完，离开再进自愈）；② 连续失败期间首页三端点持续返回 stale（不降级）；③ **三波并一波后错误语义为"全有全无"**——任一请求失败即整组不渲染，面板保留上一轮内容（冷启动为空壳）+ toast，属预期非缺陷，走查按此语义判断（勿按旧"部分渲染"口径）；④ `#report-metric` 指标 seg 与面板同容器一并减淡（见 §3）；
   - 索引写入代价备注：zcode/cc 增量导入批量事务内每行多一次 datetime() 计算+索引维护（16k+ 行量级可忽略），与存量库一次性建索引开销并列。
