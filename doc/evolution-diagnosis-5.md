# 诊断报告 EVOLUTION-5：首页 all 页签加载/切档位 0~3.5s 无反馈空窗（DSH 同步重扫为主因 + 单连接串行 + 无 loading 态）【v3】

- **日期**：2026-09-05
- **维度**：UI（反馈缺失）/性能
- **预估等级**：P2（损伤 6/10，接近 P1 线）
- **状态**：计时 + EXPLAIN 实验证据确认（v2 修订版，见文末修订记录）
- **与 20260904 问题4 的关系**：该方案 4① 已以 **v2 路线C** 部分落地（usage_records 的 `idx_usage_*_utc` + 确定性谓词，随提交 8fc12d9 签入）；4③swapping/④seq 守卫/⑤tabs 缓存已实施于**单渠道分支**；真实残留 = **DSH 同步重扫阻塞、zcode/cc 两表索引缺口、all 分支 loading/守卫缺失**。

## 问题现象

首页「全部渠道」页签（默认页签）在 DSH 缓存过期后的首次加载/切档位时，三张图表与渠道明细存在 **~3.5s 的无反馈空窗**：期间旧内容残留，无任何加载指示（实测截图 03 即空窗期实录）。

## 计时与 EXPLAIN 证据（2026-09-05 实测，v2 修订版）

### 分段实验（Python 直连 db 层 + dsh 模块）

| 环节 | 耗时 | 说明 |
|---|---|---|
| **dsh_api.get_dsh_usage()（TTL 过期后首次）** | **3494.6 ms** | **主因**：`~/.dsh/sessions` 下 **415 个 session.jsonl.zstd（压缩计 145.2 MB）**，scan() 全量解压+解析+聚合 ~3.0s（dsh_api.py:337、scan:322、TTL 15s:47）；单独调 scan() 实测 3017ms |
| usage_records 段（30d 谓词） | 0.4 ms | `SEARCH USING INDEX idx_usage_utc`——v2 已优化 |
| zcode_usage 段（30d 谓词） | 34.8 ms | `SCAN z USING COVERING INDEX idx_zcode_time`（函数包装谓词用不上纯列索引） |
| claudecode_usage 段（30d 谓词） | 18.1 ms | `SCAN c USING COVERING INDEX idx_cc_time` |
| db.report_windows（全热） | 145.5 → 92.5 ms | dsh 扫描不在 db 层；db 层本身无 3.5s 问题 |
| db.report_channels('30d') | 16.7 ms | |

### 浏览器内并发链（修订归因）

| 端点 | 并发耗时 | 修订归因 |
|---|---|---|
| /api/report/windows | 3297 ms | 端点内同步调 `get_dsh_usage()`（server.py:1067），撞上 dsh TTL 过期 → 3.5s 扫描 |
| /api/report/daily?range=30d | 3334 ms | 同窗口内被拖慢（dsh 扫描的 CPU/IO 占持 GIL + 单连接排队叠加） |
| channels/overview/zcode-quota | 46~69 ms | 正常 |

同端点单独串行：windows 第1次 3.203s（撞 dsh 过期）→ 第2次 92ms（dsh 15s TTL 命中）。

### 前端渲染

renderChannelTable 1ms / chartReportStack 8ms / chartReportDonut 2ms——瓶颈完全在后端。

## 根因（修订后）

### ① DSH 同步重扫阻塞请求线程（主因，新识别）

`get_dsh_usage()`（dsh_api.py:384-388）为"同步扫描 + 15s 模块级 TTL 缓存"模式：TTL 过期后的下一次调用在**请求线程内同步重扫 3.5s**（glob + zstd 解压 + 解析）。受影响调用点 5 处 / 端点 4 个（server.py:1067 与 1069 同在 _report_windows_response，1069 为扫描后的缓存命中调用；另 1100 channels、1288 /api/dsh/usage、1475 channel-overview dsh 分支）——`/api/report/windows`、`/api/report/channels?range=today`、`/api/dsh/usage`、`/api/report/channel-overview?channel=dsh`。**首页 all 页签每次 loadReportAll 都会调 windows/channels 端点 → 高频撞上 3.5s 重扫**。第一轮 EVOLUTION-3 已对 ZCode 配额实施过同款问题的解法（单飞+过期后台刷新+预热），dsh 未覆盖。

### ② zcode/cc 两表索引缺口（次因，20260904 方案 4① 的 v2 残留）

v2 路线C 已为 usage_records 建 `idx_usage_acct_utc/idx_usage_utc`（db.py:305/309，`datetime(created_at)` 确定性表达式索引）并将 `_report_range_sql` 改为确定性谓词（db.py:2143-2151）——**usage 段 0.4ms 已达标**。但 `zcode_usage`/`claudecode_usage` 仅有纯列索引 `idx_zcode_time/idx_cc_time`（db.py:220/247），无法服务 `datetime(z.started_at) >= datetime(?)` 函数包装谓词 → report_daily/report_windows 的 z/cc 段仍 SCAN（当前 34.8/18.1ms，随数据量线性恶化）。原诊断所称"substr+localtime 索引"方案不可行：**SQLite 禁止非确定性函数入索引**（db.py:300-302 迁移注释已记载否决理由），单参 `datetime(col)` 才可入索引。

### ③ 单连接串行放大（维持原判断）

SQLite 进程级单连接（db.py:65-78，`check_same_thread=False` + `cached_statements=0`）：ThreadingHTTPServer 每请求一线程，但查询在单连接上串行；dsh 扫描的 CPU/IO 又占持 GIL，同窗口并发请求（Promise.all 5 个）互相拖慢——daily 3.3s 的 settle 时间紧贴 windows 后 37ms 即此效应。

### ④ all 分支无 loading 指示、无过期响应守卫（维持原判断）

`loadReportAll`（app.js:2119-2146）无 `.swapping`/seq 守卫，对照单渠道分支（app.js:540-548，`++chSeq` + `classList.add("swapping")`）模式可直接对齐。另：`loadReportAll` 实为**三波瀑布**（第一波 Promise.all 4 端点 → daily → hourly），daily/hourly 与第一波无数据依赖，验证口径应覆盖全链。

## 用户体验影响

- dsh TTL 15s 过期后，首页 all 页签的任何刷新/切档位都可能撞上 3.5s 空窗（旧内容残留、无反馈）；
- zcode 数据量为主（16k+ 行），z/cc 段 SCAN 随数据增长恶化；
- 修复收益：dsh 过期后台化后 3.5s 归零；z/cc 索引后 SCAN 消除；loading 态兜底极端场景。

## 修复方向（供阶段3 细化）

1. **dsh 过期后台化**（收益最大）：`get_dsh_usage()` 对齐 EVOLUTION-3 的 `_ensure_quota_async` 惰性模式（server.py:237-267，本项目第三次复用，汇率缓存 server.py:116 同款）。显式设计点（阶段3 须逐项落地）：
   - **防重入守卫**：现状 `get_dsh_usage()` 无锁，TTL 过期时多请求线程并发会双重扫描——照 server.py:249-254 的 `_quota_refreshing` 标志模式加"刷新中"守卫；
   - **冷启动语义**：`_cache_payload is None`（进程首次）**返回 `_empty_result()` + 启动预热兜底**（server 层 `dsh_found` 分支天然兼容 found=false，首屏零阻塞，数秒后数据自愈；备选"首次阻塞扫一次"不采用，避免把 3s 带回首屏）；
   - **stale 标记**：仅进日志/debug 字段，**不改响应 schema**（前端零适配）；
   - **stale 提示显式决策：不加**——最大陈旧 ~15s+3s 对分钟/小时粒度用量面板不可感知，横幅属噪音（与"勿重复设计 SWR"取向一致）；
   - **连续失败降级**：后台重扫连续 N 次（建议 N=3）失败后，用户主动刷新降级为前台同步扫描（由加载态兜底给出反馈），防止 dsh 数据无限期冻结且零提示。
2. **zcode/cc 补建确定性表达式索引**（对齐 v2 模式）：`CREATE INDEX IF NOT EXISTS idx_zcode_utc ON zcode_usage(datetime(started_at))`、`idx_cc_utc ON claudecode_usage(datetime(started_at))`，消费方谓词（db.py:2150/2329 等）已逐字匹配、自动命中；存量库建索引一次性开销写入验收说明。
3. **all 分支补 `.swapping` + seq 守卫**（对齐单渠道模式，app.js:540-548）；**必须连带移植错误路径的加载态回收**——单渠道 catch（app.js:558-559）有 `if (seq === chSeq) remove("swapping")`，all 分支 catch（app.js:2145）现只 toast，漏掉会让 `#report-all` 永久停在 opacity .55 减淡态；daily/hourly 并入第一波 Promise.all（三波瀑布→一波单 swapping 生命周期，顺带消除 today 档 hourly 卡第三波才取消 hidden 的两段式弹入）；**SWR 等价声明（从修订记录提升）：swapping 不清空旧 DOM，补齐 loading+守卫即隐式达成 stale-while-revalidate，禁止再设计独立 SWR 缓存**；守卫序号与单渠道 `chSeq` 的共用/独立关系在阶段3 定义（all↔单渠道往返需级联失效）。排期提示：本项纯前端、零后端依赖，可先行合入，不被后端复测阻塞。
4. **可选（优先级降低）**：windows 响应 TTL 缓存——dsh 后台化后 windows 热态仅 92ms，缓存收益有限；若做，失效清单须写实（复用 `_invalidate_overview_cache` 现有 6 个调用点 + today/yesterday 档 TTL≤1s 或不缓存 + 缓存键含 channel）。

## 验证点（修订后）

- dsh TTL 过期后首页 all 刷新不再出现 3.5s 空窗（stale 值即时返回）；
- 并发链全链（含 daily/hourly）耗时 < 500ms；**后台重扫进行中窗口期**复测全链耗时（GIL 残留风险兜底；若仍明显拖慢，子进程扫描列为阶段3 备选、不进本方案）；
- EXPLAIN：usage 段已 `USING INDEX`（现状达标），验收 **zcode/cc 两段由 SCAN 变 `USING INDEX`**；
- all 分支出现加载态；快速连点 4 档位、all↔单渠道快速往返、**档位×指标（app.js:2105 同入 loadReportAll）双维快速切换**，终态与最后一次点击一致；
- **失败路径**：模拟请求失败后 all 分支恢复正常透明度并保留旧内容（加载态回收）；
- **连续失败降级路径**：模拟后台重扫连续失败后，主动刷新走前台扫描并给出加载反馈；
- today 档目测内容单次成块出现（无两段式弹入）；
- 单渠道分支行为不回归（chSeq 语义）。
- 实验环境备注：dsh 环境为 415 个会话文件/145.2 MB（压缩）；他人复现计时数值需按自身 dsh 数据量折算。

---

## 修订记录

- **v3（2026-09-05，门禁1 第 2 轮 3/3 通过后吸收建议修订）**：补 dsh 环境数据（415 文件/145.2MB，更正 v2 检查时误用 `~/.dsh` 而非 `~/.dsh/sessions` 的环境描述）；"5 处"更正为 5 调用点/4 端点；dsh 后台化补齐五个显式设计点（防重入/冷启动语义/stale 标记/不加提示决策/连续失败降级）；修复方向3 补 catch 加载态回收与 SWR 声明提升正文；验证点补失败路径、降级路径、双维切换、重扫窗口期复测、today 档观感与实验环境备注。
- **v2（2026-09-05，门禁1 第 1 轮两席驳回后修订）**：撤销原根因①"4① 表达式索引未实施"——为**假阴性**（grep 用了旧方案名 `idx_usage_day`，实际 v2 已以 `idx_usage_*_utc` 落地并随 8fc12d9 签入）；撤销原修复方向 1 的 substr+localtime DDL（SQLite 禁止非确定性函数入索引，不可执行）；新增主因①（dsh 同步重扫 3.5s，分段实验发现）；根因② 改写为 zcode/cc 两表索引缺口；补 SWR 等价关系（swapping 不清旧 DOM，补齐即隐式达成，勿重复设计独立 SWR 缓存）；补三波瀑布与全链验证口径；windows 缓存降为可选项。原 v1 的"单连接串行/无 loading 态"判断经评委核实成立，保留。
