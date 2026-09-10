# Task 5 验证与记录报告

日期：2026-09-10

状态：完成。新增回归覆盖、两处由执行测试证实的最小 UI 修复，以及只读本机 DSH 抽验均已完成。

复核修正：初版的 V8 race 使用阻塞延时，不能证明旧响应实际晚到；V9 的本地 fixture仍含远程形态，并且主题/语言测试离开了统计页。以下矩阵已按修正后的可执行证据重写。

## 本次改动

- `tests/test_dsh_ui_playwright.py`：真实 `app/web` 静态服务 + 全 API 拦截的 Playwright 覆盖。测试设 5 秒默认超时，实际启动本机 Chromium，不依赖登录或真实日志；旧 7d 请求会被路由保持未决，30d 新响应先渲染，释放旧响应后 UI 仍保持 30d。
- `tests/test_dsh_api.py`：验证同一 TTL 内 `today/yesterday/7d/30d/all` 共用冻结快照，范围切换不会再次解压日志。
- `tests/test_report_api.py`：补齐 `all` 的 180/181 天粒度门槛、跨年 `W00` 标签及单渠道隔离；固定 Asia/Shanghai 时间的四步骤快照经 `query_dsh_usage` 后进入 windows、dashboard、daily、hourly 适配器。
- `app/web/app.js`：补页面可见性处理和按范围管理的在途 DSH 请求。统计页进入后台时销毁图表并取消所有在途请求/轮询；回到前台立即按当前范围刷新。`/api/state` 也暴露 `dsh_found`，让无远程账户、无 Codex 的纯 DSH 本地模式解除登录遮罩。
- `app/web/style.css`：为 DSH 双表容器加横向滚动，保证窄窗口可用。
- `tests/test_theme_rerender.py`：迁移旧的 10 图表断言为当前 11 图表，纳入 DSH 趋势图，断言仍严格检查 `noAnim`。

后两项 UI 修复均由新的浏览器测试先复现：隐藏页面不会取消 1.5 秒 DSH 轮询，且 `#dsh-tables` 的 `overflow-x` 为 `visible`。修复后均由相同测试验证。

## V1–V10 验收

| 项目 | 证据 | 结果 |
|---|---|---|
| V1 | 混合有效/无效秒速、加权聚合、provider/model/总量，以及日趋势总量勾稽 | 通过 |
| V2 | 自然日、今日/昨日/7d/30d 精确第 7/30 天排除、DST 25 小时与重复 1 时桶、未来/无日期及跨午夜重新分桶 | 通过 |
| V3 | chunk/message 最终值、晚到 chunk 不覆盖 final message、后续 final message 修正、归属切换、缺 key 可观测与会话身份 | 通过 |
| V4 | TTL、惰性刷新防重入、失败退避/恢复、热缓存保留、公开序列化 | 部分通过；真实多线程 `scan_sync` 与 worker 写缓存碰撞未覆盖 |
| V5 | 固定 Asia/Shanghai 四步骤快照（缓存输入、零秒无效测速、同会话）经实际范围查询后覆盖 windows、dashboard、daily/hourly | 通过 |
| V6 | 纯 DSH、合并跨度、180/181 天、跨年 `W00`、单渠道隔离测试 | 通过 |
| V7 | 费用/请求未知、空范围、比较排除 DSH、其他渠道不查询 DSH 测试 | 通过 |
| V8 | Playwright 实际点击四个统计档位、五个首页档位、保持未决旧 7d 响应并在新 30d 渲染后释放、零/无速度/扫描/失败状态；真实 Canvas tooltip 悬停断言日期及数值 | 通过（Chromium） |
| V9 | Playwright 无远程账户/无 Codex 的纯 DSH 本地模式；统计页可见时语言/主题重绘缓存图表且无额外 DSH 请求；隐藏页销毁图表、取消未决请求、停轮询并前台立即刷新；900px 真实溢出并可改变 `scrollLeft` | 通过（Chromium） |
| V10 | 自动回归断言冻结快照范围切换不会解压；只读本机抽验 | 通过 |

未验证项：V4 的真实多线程 `scan_sync` 与后台 worker 同时扫描/写缓存碰撞。当前实现使用模块级赋值而没有显式锁；既有确定性测试只覆盖惰性刷新不重入。该缺口未伪装为已验证。

## 验证结果

```text
python -X utf8 -m pytest [DSH/report/UI focused suites] -q
137 passed, 3 skipped in 12.38s

python -X utf8 -m pytest tests -q
635 passed, 3 skipped in 91.27s

node --check app/web/app.js
exit 0

git diff --check
exit 0
```

Playwright 的两项用例在 Chromium 上通过；默认超时为 5 秒，完整运行约 8 秒。三个跳过项为已有的本地时段前置条件跳过，未由本任务新增。

## 复核后验证

```text
python -X utf8 -m pytest tests/test_dsh_api.py tests/test_dsh_background.py tests/test_report_api.py tests/test_dsh_ui_contract.py tests/test_dsh_ui_playwright.py -q
79 passed, 3 skipped in 12.23s

node --check app/web/app.js
exit 0
```

## 第二轮复核修正

- DSH 请求不再用全局序号拒绝一个“先发 7d → 显示 30d → 回到 7d”的原始 7d 响应。接收条件以当前可见范围为准：不同范围的迟到响应继续丢弃，用户已返回的同范围响应可渲染。Playwright 断言释放原 7d 后 `state.statsRange` 与 `dshUsageLast.range` 都为 `7d`，且 KPI 显示 700。
- parser 回归拆成两次扫描：先验证 late chunk 不会覆盖第一个 final message，再追加更晚的 final message 验证修正生效，避免后者掩盖前者。
- 隐藏页测试先接收 scanning 响应并断言真实 `dshRefreshTimer` 已创建；隐藏后断言其为 `null` 且等待一个 poll 周期无请求。另行保持一条请求未决，隐藏后断言图表销毁且 `dshRequestControllers.size === 0`。

```text
python -X utf8 -m pytest tests/test_dsh_api.py tests/test_dsh_ui_contract.py tests/test_dsh_ui_playwright.py -q
42 passed in 10.51s

node --check app/web/app.js
exit 0
```

## 第三轮复核修正

- 修复范围往返：保持 7d 请求未决、让 30d 先渲染、再选择 7d 后释放最初请求。全局序号会把该响应当作过期而导致 30d 内容留在活跃 7d 下；现在仅当响应范围不是当前范围或统计页不可见时丢弃。Playwright 最终断言 `state.statsRange === "7d"`、`dshUsageLast.range === "7d"`，且 DSH KPI 显示 700。
- parser 用例先单独断言 `message + late chunk` 保留首个 final 消息，再以第二次扫描断言更晚 final message 的更正，两个行为互不掩盖。
- 隐藏页先建立 scanning 定时器并断言 `dshRefreshTimer !== null`；隐藏后断言 timer 清空且一轮 poll 内无请求。未决请求场景单独断言 `dshRequestControllers.size === 0`。
- 全量测试在本地零点后暴露三个既有测试 fixture 将“今天减 10 分钟/1 小时”写入昨天；只修正 fixture 的本地日期保护，未更改生产报表逻辑。

```text
python -X utf8 -m pytest tests/test_commandcode_sync.py::test_dashboard_commandcode_uses_charts_aggregate tests/test_report_api.py::test_report_hourly_and_totals_local_dispatch tests/test_report_api.py::test_channel_totals_zero_fallback_and_hit_rate tests/test_dsh_api.py tests/test_dsh_ui_contract.py tests/test_dsh_ui_playwright.py -q
45 passed in 10.78s

python -X utf8 -m pytest tests -q
639 passed, 3 skipped in 93.33s

node --check app/web/app.js
exit 0
```

## V10 只读本机证据

在一次 `dsh_api.scan()` 冻结快照上执行范围聚合，没有写入、移动或提交任何本机日志：

- 有效日期覆盖：2026-08-13 至 2026-09-10，共 24 个自然日。
- 当日趋势日合计与当日范围总量相等。
- 将该快照置为同 TTL 缓存后查询 `today/7d/30d/all`，`decompress_frames` 调用次数为 0。
- 首次只读扫描约 3.67 秒；缓存快照约 15k 步，符合本机规模记录需要。

报告只记录匿名的覆盖、耗时和缓存规模；未写入 token、模型、会话路径、日志正文或任何本机用户数据。
