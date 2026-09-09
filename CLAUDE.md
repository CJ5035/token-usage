# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

GoGauge — 本地优先的 OpenCode Go 用量统计面板(Python 桌面应用)。pywebview(WebView2) 渲染前端,SQLite 本地存储,从 opencode.ai 官方接口同步配额与用量记录。打包为单文件 exe(Windows)。

## 常用命令

```bash
# 安装依赖
pip install -r requirements.txt

# 源码运行 (Windows 需 WebView2 Runtime; 会弹应用窗口, 调试时观察 stderr)
python entry.py

# 运行测试 (conftest.py 已把仓库根加入 sys.path)
python -m pytest
python -m pytest tests/test_db_multiuser.py -k "migration"

# 打包单文件 exe (PyInstaller --onefile --noconsole)
build.bat   # 输出 dist\GoGauge.exe
```

## 架构

进程启动: `entry.py` → `app/main.py:main()` → 启动本地 HTTP 服务 → 创建 frameless WebView 窗口 → 未登录显示欢迎页,登录后进面板。

### 分层

| 模块 | 职责 |
|---|---|
| [app/main.py](app/main.py) | 窗口/托盘/单实例守卫/登录窗口编排;`WindowApi` 以 js_api 暴露窗口控制(最小化/拖动/关闭) |
| [app/server.py](app/server.py) | 本地 HTTP 服务(127.0.0.1 随机端口)+ 全部 JSON API + 后台同步调度 |
| [app/db.py](app/db.py) | SQLite 单例连接、建表迁移、聚合查询 |
| [app/opencode_api.py](app/opencode_api.py) | OpenCode Go API 客户端:配额 HTML 正则解析 + `_server` server-fn 用量接口解析 |
| [app/auth.py](app/auth.py) | WebView 登录:加载官方授权页,轮询捕获 `auth` cookie 与工作区 ID |
| [app/updater.py](app/updater.py) | GitHub Releases 更新检查(API 优先,Atom 流降级) |
| [app/web/](app/web/) | 前端:vanilla JS + Chart.js + 中英 i18n,经 HTTP fetch 调 `/api/*` |

### 关键机制

- **前后端边界**: 前端只用 `fetch('/api/*')` 与后端通信;`js_api`(WindowApi) 仅做窗口操作。新增页面数据接口都走 server.py 的 `_handle_api`。
- **多账号模型**: `accounts` 表多行,`usage_records.account_id` 归属账号,`usage_sync_state` 以 account_id 为主键每账号一份游标。`settings.payload` JSON 存 `active_account_id` 与 `key_names`(key_id→显示名 映射)。兼容约定:db.py 函数不显式传 account_id 时一律作用于**活跃账号**(`get_active_account_id`)。
- **同步**: `incremental`(每账号最多 5 页=250 条,顺序轮询所有已登录账号)/ `full`(仅活跃账号,2000 页上限,遇窗口边界停)。页并发拉取 `FETCH_BATCH=5`。`usage_records` 以 `usg_id` 主键 upsert 去重。进度经 `_sync_state` 全局 dict + 锁跨线程共享,前端轮询 `/api/dashboard` 拿 `progress`。
- **配额缓存**: `fetch_quota` 抓 dashboard HTML 正则解析(字段顺序有两种,见 `parse_quota_html`),按账号分槽缓存 30s TTL,过期后台线程刷新(`_ensure_quota_async`),不阻塞 dashboard 响应。
- **口径约定**: `total_input_tokens = input + cache_read + cache_write_5m + cache_write_1h`;`hit_rate = cache_read / (cache_read + input + cache_write)`;`cost_raw` 单位 1e-8 USD,`cost_usd = cost_raw / 1e8`。改聚合口径需同步 db.py 全渠道聚合函数（totals/model_stats/daily_stats/_totals_from_row/_charts_*_dict/zcode_*/claudecode_*/codex 系，见 doc/20260907-hit-rate-formula-fix.md 清单 15 处）。
- **数据目录**: 开发模式 `data/`(仓库根);打包后 exe 同目录 `data/`,不可写回退 `LOCALAPPDATA/GoGauge/data`。可用环境变量 `GOUSAGE_DATA` 覆盖。
- **登录流**: `LoginWatcher` 轮询登录窗 URL/cookie,成功后按 `pending_mode`("add"=新建账号 / "relogin"=更新活跃账号凭证)落库,再触发全量同步。登录窗可被手动关闭,`_recreate_login_window` 负责重建。

## 数据库 Schema(核心表)

- `usage_records`: 主键 `usg_id`;token 明细列(input/output/reasoning/cache_read/cache_write_5m/cache_write_1h);`cost_raw/cost_usd`;`key_id/session_id/plan`;`account_id` 索引 `(account_id, created_at DESC)`。
- `accounts`: 每账号 name/workspace_id/resolved_workspace_id/token。
- `usage_sync_state`: account_id 主键,增量游标与统计。
- `settings`: 单行 JSON payload(白名单键见 `db._DEFAULT_SETTINGS`,另有 `active_account_id`/`key_names`)。

存量迁移都在 `db._init_schema` 内幂等执行(旧单账号表→多账号表的 3 步迁移),改动 schema 需兼容旧库并补迁移。

## 前端要点

- 单页 `index.html` + `app.js`(无框架,无构建步骤)。页面切换、渲染、图表、i18n 都在 app.js。
- i18n: `I18N.zh/en` 字典 + `data-i18n` 属性,新增文案必须同时补两种语言。
- 图表 Chart.js(`chart.umd.min.js` 本地 vendored);主题亮/暗经 CSS 变量 + `data-theme`。
- 模型图标在 `app/web/icons/`,按模型名匹配(`modelIcon`)。
