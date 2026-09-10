# Task 5 验证与记录报告

日期：2026-09-10

状态：完成。新增回归覆盖、两处由执行测试证实的最小 UI 修复，以及只读本机 DSH 抽验均已完成。

## 本次改动

- `tests/test_dsh_ui_playwright.py`：新增真实 `app/web` 静态服务 + 全 API 拦截的 Playwright 覆盖。测试设 5 秒默认超时，实际启动本机 Chromium，不依赖登录或真实日志。
- `tests/test_dsh_api.py`：验证同一 TTL 内 `today/yesterday/7d/30d/all` 共用冻结快照，范围切换不会再次解压日志。
- `tests/test_report_api.py`：补齐 `all` 的 180/181 天粒度门槛、跨年 `W00` 标签及单渠道隔离。
- `app/web/app.js`：补页面可见性处理。统计页进入后台时销毁 DSH 图表并取消轮询/在途请求；回到前台立即按当前范围刷新。
- `app/web/style.css`：为 DSH 双表容器加横向滚动，保证窄窗口可用。
- `tests/test_theme_rerender.py`：迁移旧的 10 图表断言为当前 11 图表，纳入 DSH 趋势图，断言仍严格检查 `noAnim`。

后两项 UI 修复均由新的浏览器测试先复现：隐藏页面不会取消 1.5 秒 DSH 轮询，且 `#dsh-tables` 的 `overflow-x` 为 `visible`。修复后均由相同测试验证。

## V1–V10 验收

| 项目 | 证据 | 结果 |
|---|---|---|
| V1 | `test_dsh_api.py` 的混合有效/无效秒速、加权聚合、provider/model/总量测试 | 通过 |
| V2 | 自然日、今日/昨日/7d/30d、DST、未来/无日期及跨午夜重新分桶测试 | 通过 |
| V3 | chunk/message 最终值、归属切换、缺 key 可观测与会话身份测试 | 通过 |
| V4 | TTL、并发仅一次扫描、失败退避/恢复、热缓存保留、公开序列化测试 | 通过 |
| V5 | 固定四步骤快照覆盖 windows、channels、dashboard、daily/hourly、overview、trend 与未知费用/请求语义 | 通过 |
| V6 | 纯 DSH、合并跨度、180/181 天、跨年 `W00`、单渠道隔离测试 | 通过 |
| V7 | 费用/请求未知、空范围、比较排除 DSH、其他渠道不查询 DSH 测试 | 通过 |
| V8 | Playwright 实际点击四个统计档位、五个首页档位、乱序范围响应、零/无速度/扫描/失败状态；真实 Canvas tooltip 悬停断言日期及数值 | 通过（Chromium） |
| V9 | Playwright 纯本地无登录、语言/主题无请求重绘、隐藏页停轮询并前台立即刷新、1280×840 与 900×700 窄布局及表格横向滚动 | 通过（Chromium） |
| V10 | 自动回归断言冻结快照范围切换不会解压；只读本机抽验 | 通过 |

没有未验证的 V 项目。

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

## V10 只读本机证据

在一次 `dsh_api.scan()` 冻结快照上执行范围聚合，没有写入、移动或提交任何本机日志：

- 有效日期覆盖：2026-08-13 至 2026-09-10，共 24 个自然日。
- 当日趋势日合计与当日范围总量相等。
- 将该快照置为同 TTL 缓存后查询 `today/7d/30d/all`，`decompress_frames` 调用次数为 0。
- 首次只读扫描约 3.67 秒；缓存快照约 15k 步，符合本机规模记录需要。

报告只记录匿名的覆盖、耗时和缓存规模；未写入 token、模型、会话路径、日志正文或任何本机用户数据。
