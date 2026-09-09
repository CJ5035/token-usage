# Bug 诊断报告：DSH 用量获取逻辑

- **日期**：2026-09-07
- **状态**：已确认（4 项缺陷 + 5 项优化点，均附验证动作；未改任何代码）
- **严重级别**：最高 P2（无 P0/P1；主链路功能正常，31 个 DSH 测试全部通过）
- **报告人**：ZCode Agent（Bug Diagnosis Skill）

---

## 问题描述

排查 DSH（本机 dsh CLI，`~/.dsh/sessions` 日志）用量获取逻辑：`app/dsh_api.py` 全量扫描 + 15s TTL 缓存 + 后台刷新，经 `app/server.py` 三个 report 端点与 `/api/dsh/usage` 端点供前端 `app/web/app.js` 渲染。判断是否存在 bug 或使用体验优化点，并给出修复建议。

## 环境信息

- 分支/版本：main @ 83b2369
- 相关模块：`app/dsh_api.py`（核心）、`app/server.py:1064-1111,1287-1297,1478-1501`（端点）、`app/main.py:476-478`（启动预热）、`app/web/app.js:966-1051,2232,2331-2355`（前端）
- 测试基线：`tests/test_dsh_api.py` + `tests/test_dsh_background.py` 共 31 例全部通过
- 复现步骤：见各项"验证动作"

---

## 第一步：可能原因分析（按概率排序）

> 本任务为主动体检而非特定故障，故"原因"= 排查中实际确认的缺陷/风险点。

| # | 问题 | 级别 | 概率 | 理由 |
|---|------|------|------|------|
| 1 | 冷启动空窗误报"未检测到 DSH 本地数据"（found=false 语义混淆"没扫完"与"没数据"） | P2 | 高（每次冷启动必现窗口期） | `get_dsh_usage` 冷启动返回 `_empty_result()`（found=false），前端渲染引导文案；预热扫描未完成时用户进统计页即误报 |
| 2 | turn/step 缺失时 usage 挤在 "0:0" 键互相覆盖 → 漏统计 | P2 | 中（取决于现网日志是否总有 turn/step） | `_usage_key` 对缺失字段兜底 "0:0"，同会话多条缺失事件只留最后一条；`step_starts` 同样覆盖 |
| 3 | degraded（连续失败 3 次）后首页 DSH 数据无限冻结；`scan_sync` 无防重入 | P2 | 低（scan 吞掉单文件错误，极难连续失败 3 次） | report 端点直调 `get_dsh_usage()` 不走降级，stale 永不刷新；ThreadingHTTPServer 并发请求可并发全量扫描 |
| 4 | `sessions_count` 把损坏/不可读文件也计入"会话数" KPI | P3 | 高（有坏文件即触发） | `scan()` 中 `len(files)` 在 `stat_log` 过滤前取得 |
| 5 | 渠道表 dsh 行 `cache_read` 混入 cacheWrite（口径失真） | P3 | 高（cacheWrite>0 即失真） | `cache = cacheRead + cacheWrite` 合并后塞进 `cache_read` 字段 |
| 6 | `/api/report/windows?channel=dsh` 为死分支且口径有误导隐患 | P3 | 确认（前端仅一处无参调用） | `yesterday/7d/30d` 全填今日值、无 `today_only` 标志（channel-overview 有） |
| 7 | 停留统计页期间 DSH 数据不更新；跨午夜后"今日"桶停留昨日快照 | P3 | 高（设计取舍，非故障） | 无自动轮询（注释明示），仅切页/切语言触发 |
| 8 | 全量重扫无增量：每 15s 后台全量解压全部历史会话文件 | P3 | 高（会话多时 CPU 周期性峰值） | `scan()` 每轮对所有 `*/*/session.jsonl.zstd` 重新解压统计 |
| 9 | zstd 魔数切分的理论漏算（压缩内容偶现 4 字节魔数 → 错误切分丢帧） | P3 | 极低 | 概率约 文件字节量/2³²，漏算不崩溃；务实取舍，记录为已知限制 |

另排查后**排除**的嫌疑：`_refreshing` check-then-set 竞态（GIL 下窗口极小，后果仅重复扫描，且注释明示对齐 `server.py _ensure_quota_async` 既有模式，不建议单独加锁破坏一致性）；本地时区"今日"判定（`_today_start_ms` 用本地零点 epoch ms 与事件绝对时间比较，正确）；缓存对象本体透传（GIL 引用替换原子 + 前端只读约定，自洽）。

---

## 第二步：验证动作

### 针对问题 1：冷启动误报"未检测到 DSH 本地数据"

- **验证方式**：启动观察 + curl
- **位置**：`app/dsh_api.py:405`（冷启动返回空态）、`app/web/app.js:1005-1010`（found=false → dshStatsMissing 文案）
- **具体操作**：
  1. 确保 `~/.dsh/sessions` 存在且会话文件较多（扫描耗时 >1s）
  2. 启动应用后 1~2 秒内切到统计页
  3. 同时另开终端：`curl http://127.0.0.1:<port>/api/dsh/usage`
- **预期结果**：页面显示"未检测到 DSH 本地数据（~/.dsh/sessions）"，curl 返回 `"found": false`；数秒后重新切页才恢复正常数据 —— 误报成立。

### 针对问题 2：turn/step 缺失导致漏统计

- **验证方式**：脚本抽样统计真实日志
- **位置**：`app/dsh_api.py:135-137`（`_usage_key` 兜底 "0:0"）、`app/dsh_api.py:224/235/242`（三处 dict 覆盖写入）
- **具体操作**：

  ```python
  # python - <<'EOF'
  from app import dsh_api
  from pathlib import Path
  import json
  miss = total = 0
  for p in Path.home().joinpath(".dsh/sessions").glob("*/*/session.jsonl.zstd"):
      for line in dsh_api.decompress_frames(p.read_bytes()).splitlines():
          if '"assistant/message"' not in line and '"assistant/chunk"' not in line:
              continue
          try:
              e = json.loads(line)
          except ValueError:
              continue
          d = e.get("data") or {}
          if isinstance(d.get("usage"), dict) or (isinstance(d.get("chunk"), dict) and d["chunk"].get("type") == "usage"):
              total += 1
              if "turn" not in d or "step" not in d:
                  miss += 1
  print(f"usage 事件 {total} 条, 缺 turn/step {miss} 条")
  # EOF
  ```

- **预期结果**：`miss > 0` 则问题成立（这些会话会被少算）；`miss == 0` 且覆盖全部历史日志版本，可降级为"防御性修复"。

### 针对问题 3：degraded 后数据冻结

- **验证方式**：单测注入（monkeypatch `scan` 连续抛异常）
- **位置**：`app/dsh_api.py:402`（`_fail_count < 3` 后永不 spawn）、`app/server.py:1068/1102/1483`（report 端点直调 `get_dsh_usage` 不走降级）
- **具体操作**：参照 `tests/test_dsh_background.py::test_degraded_boundary`，让 `scan` 抛异常 3 次后调 `get_dsh_usage()`，再向 sessions 写入新数据、调 `scan` 恢复正常，再次调用 `get_dsh_usage()`。
- **预期结果**：恢复后 `get_dsh_usage()` 仍返回旧 stale（不再自动重扫）；只有 `scan_sync()` 才能解冻 —— 冻结成立。

### 针对问题 4：会话数虚高

- **验证方式**：构造坏文件
- **位置**：`app/dsh_api.py:337-347`（`len(files)` 先于 `stat_log` 过滤）
- **具体操作**：在 `~/.dsh/sessions/a/b/session.jsonl.zstd` 放一个纯文本文件，调 `dsh_api.scan()`。
- **预期结果**：`sessions_count == 1` 但 `total` 全 0 —— 计数与数据不一致。

---

## 第三步：调用链与依赖分析

### 完整调用路径

```
[启动预热] main.py:478 dsh_api.get_dsh_usage()
    └─ 冷启动 spawn _rescan_worker (daemon)                      [dsh_api.py:404,427]

[统计页] app.js:497 showPage("stats") → loadDshUsage             [app.js:974]
    └─ GET /api/dsh/usage                                        [server.py:1287]
        ├─ degraded()? ── 是 → scan_sync() 同步全量扫描           [dsh_api.py:413]  ← 无防重入
        └─ 否 → get_dsh_usage()                                  [dsh_api.py:390]
            ├─ TTL(15s) 内 → 返回 _cache_payload
            └─ 过期 → 返 stale + spawn _rescan_worker
                └─ scan()                                        [dsh_api.py:323]
                    └─ stat_log() ← decompress_frames()          [dsh_api.py:163,65]
[首页-全部] app.js:2232 GET /api/report/windows                   [server.py:1451]
    └─ _report_windows_response                                  [server.py:1064]
        └─ get_dsh_usage() 今日 tokens 并入 payload["today"]      [server.py:1068-1079]
[首页-渠道表] app.js:2233 GET /api/report/channels                [server.py:1472]
    └─ _report_channels_response                                 [server.py:1097]
        └─ get_dsh_usage() 追加 dsh 行 (cache_read 口径失真点)     [server.py:1105-1109]
[首页-单渠道] app.js:563 GET /api/report/channel-overview         [server.py:1478]
    └─ dsh 分支 (唯一带 today_only 标志的出口)                    [server.py:1482-1491]
```

### 关键依赖节点

- **上游调用者**：`main.py:478`（预热）、`server.py` 4 个 GET 端点、前端 `loadDshUsage`
- **下游依赖**：本地文件系统 `~/.dsh/sessions/*/*/session.jsonl.zstd`（zstd 多帧流）、`zstandard` 库；不依赖数据库与网络
- **数据流**：zstd 解压 → JSONL 逐行过滤（`_INTERESTING_TYPES` 子串预过滤）→ request/context 声明渠道×模型 → chunk/message 的 usage 按 turn:step 去重覆盖 → 按 provider/model/today 分桶聚合 → 模块级 TTL 缓存 → server 只读透传 → 前端只读渲染

### 影响范围评估

若修改 `dsh_api.py`（如 BUG-2 的 key 策略、OPT-4 的增量缓存）：
- 直接影响 `server.py` 4 个端点的响应字段（`found`/新增 `scanning` 等需前端同步）
- `tests/test_dsh_api.py`（20 例）+ `tests/test_dsh_background.py`（11 例）需同步扩展
- 缓存对象"只读透传、严禁原地修改"约定（`server.py:1289-1290`、`app.js:971`）必须保持

---

## 第四步：边缘情况检查

| 维度 | 场景 | 当前行为 | 是否有问题 | 建议 |
|------|------|----------|------------|------|
| 空值/缺失 | 日志事件缺 turn/step | 全部兜底 "0:0" 互相覆盖，只留最后一条 | **是**（BUG-2） | key 改用事件序号/时间戳兜底保唯一 |
| 空值/缺失 | usage 缺 input+output | `_tokens_from_usage` 返回 None 跳过 | 否 | — |
| 空值/缺失 | 目录不存在/为空 | `found=false` 空态，不抛异常 | 否 | — |
| 冷启动 | 预热未完成即请求 | 返回 found=false 空态 → 前端误报"无数据" | **是**（BUG-1） | 增加 `scanning` 状态字段区分 |
| 并发 | TTL 过期瞬间多请求 | `_refreshing` check-then-set 可能 spawn 多个扫描线程 | 轻微（接受） | 与既有 `_ensure_quota_async` 模式一致，GIL 下窗口极小，不单独改 |
| 并发 | degraded 时并发请求 | `scan_sync` 无防重入，多次并发全量扫描 | **是**（并入 BUG-3） | 降级路径加防重入或低频后台重试 |
| 超时/失败 | 单文件损坏/半帧 | 坏帧丢弃、文件跳过，不外抛 | 部分（BUG-4 计数虚高） | 会话数按成功统计的文件数计 |
| 超时/失败 | 后台扫描连续失败 ≥3 | 降级：仅 `/api/dsh/usage` 同步扫描可恢复；report 端点 stale 冻结 | **是**（BUG-3） | report 端点同走降级判定，或允许低频后台重试 |
| 数据边界 | 单步 output<10 / 窗口≤0 / >500 tok/s / 无 step/start | 不计秒速，token 照计（有测试覆盖） | 否 | — |
| 数据边界 | zstd 多帧流 / 截断尾帧（正在写入） | 逐帧切分，`eof=False` 尾帧丢弃 | 否（设计如此） | 魔数碰撞为理论漏算（极低），记录为已知限制 |
| 时间边界 | 跨午夜 | "今日"桶按本地零点切分正确；但无轮询，快照停留至下次切页 | 轻微（OPT-3） | 统计页可见时低频轮询（可选） |
| 口径一致性 | dsh cacheRead+cacheWrite | 合并进 `cache`，渠道表塞 `cache_read` 列展示 | **是**（OPT-1，P3） | 拆分两字段或行内标注口径 |
| 口径一致性 | `report/windows?channel=dsh` | yesterday/7d/30d 填今日值、无 today_only 标志、前端无调用方 | **是**（OPT-2，死分支） | 删除或补 `today_only: True` 对齐 channel-overview |
| 环境差异 | `~/.dsh/sessions` 权限拒绝 | `root.glob` 异常向上抛 → 后台记退避 / 同步路径 500 | 与 BUG-3 同链路 | 同 BUG-3 |
| 性能 | 会话文件多（千级×数 MB） | 每 15s 后台全量解压全部历史 | **是**（OPT-4） | 按 (path, mtime, size) 缓存单文件结果，仅重扫变化文件；注意跨午夜时"今日"桶失效处理 |

---

## 总结与建议

**一句话结论**：DSH 用量获取主链路（扫描→聚合→缓存→渲染）功能正确、测试覆盖良好，但存在 **1 个高概率体验缺陷（冷启动误报"无数据"）、1 个边界数据正确性缺陷（turn/step 缺失漏统计）、1 个低概率可用性缺陷（degraded 后数据冻结）**，以及会话数虚高、cache 口径失真、死分支、无增量扫描等 P3 优化点。

**建议修复优先级**（供确认后立项，遵循"先文档确认再改码"约定）：

| 优先级 | 项 | 改动面 | 预估工作量 |
|--------|----|--------|-----------|
| P2-1 | BUG-1 冷启动误报：`get_dsh_usage` 冷启动且 `_refreshing` 时附 `scanning: true`，前端 `renderDsh` 显示"扫描中…"占位 | dsh_api.py + app.js + i18n 两语言 + 测试 | 小 |
| P2-2 | BUG-2 漏统计：`_usage_key` 缺失兜底改唯一键（行号/时间戳）；先跑第二步抽样脚本确认现网命中率再决定是否升级优先级 | dsh_api.py + 测试 | 小 |
| P2-3 | BUG-3 降级冻结：report 三端点同走 `degraded()` 判定（或 `scan_sync` 加防重入 + 低频后台重试） | server.py + 测试 | 中 |
| P3 | BUG-4 会话数、OPT-1 cache 口径、OPT-2 死分支、OPT-4 增量扫描（收益最大但改动最大，建议单独立项） | 各自独立 | 中 |

不建议修改项：`_refreshing` 竞态（对齐既有模式，收益不抵一致性破坏）、zstd 魔数切分（务实取舍，记录为已知限制）。
