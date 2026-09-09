# README 内容更新实施文档

日期：2026-09-09
类型：文档更新（不涉及代码改动）

## 1. 背景与问题

当前 `README.md` / `README_en.md` 的内容停留在早期版本，与代码现状不一致：

| 项 | README 现状 | 代码实际（v2.2.0） |
|---|---|---|
| 产品定位 | OpenCode Go 单渠道仪表盘 | 多渠道聚合面板，7 个数据源 |
| 数据源 | OpenCode Go + Codex 本地 | OpenCode / BAI / CommandCode（云端登录）+ ZCode / Claude Code / Codex / DSH（本机免登录） |
| 功能列表 | 无全渠道报表、数据源分层统计、账户总览 | 首页全渠道报表（`/api/report/*`）、统计页分层视图、账户总览页均已上线 |
| 使用记录口径 | 「记录页不含 Codex」 | 已升级为统一来源明细（`db._unified_source_sql` 四表 UNION：usage_records + zcode + claudecode + codex），记录页来源筛选含全部 6+1 渠道 |
| 费用/货币 | 仅 CNY 换算说明 | 设置页已支持默认货币 CNY/USD 切换；各渠道费用口径不同 |
| 技术栈 | 未提 zstandard | DSH 日志解压依赖 zstandard（requirements.txt 已含） |

## 2. 修改目标

依据代码更新两份 README 的描述，使其与 v2.2.0 实际功能一致：

1. 标题/副标题改为多渠道定位（参考前端「关于」页文案口径）
2. 功能列表补全：全渠道报表、数据源分层统计、统一来源记录、账户总览、货币切换、自动更新等
3. 数据说明改为「分渠道数据来源」表格 + 统一口径说明（总 Token / 缓存命中率 / 费用估算来源）
4. Codex 小节更新：记录页已含 Codex（统一来源筛选），删除过时的「当前阶段不含」表述
5. 保留测试契约要求的 `GOUSAGE_CODEX_HOME` 字样（`tests/test_codex_ui_contract.py:49`）

## 3. 修改文件

- `README.md`（中文）
- `README_en.md`（英文）

不改动任何代码；截图引用路径不变（assets/screenshots/ 下 7 张图均存在）。

## 4. 事实来源（代码依据）

- 数据源清单：`app/server.py:1231-1233`（`_STATS_ALL_SOURCES = opencode, bai, commandcode, zcode, claudecode, codex, dsh`）
- 各模块 docstring：`app/opencode_api.py`、`app/bai_api.py`、`app/commandcode_api.py`、`app/zcode_api.py`、`app/claudecode_api.py`、`app/codex_api.py`、`app/dsh_api.py`
- 页面结构：`app/web/index.html`（home/stats/records/overview/settings/about 六页）
- 统一来源明细：`app/db.py:3829` `_unified_source_sql`、`app/web/app.js` SOURCE_OPTIONS
- 版本：`app/__init__.py` `__version__ = "2.2.0"`

## 5. 验证方式

```bash
# 1) README 契约测试（GOUSAGE_CODEX_HOME 字样）
python -m pytest tests/test_codex_ui_contract.py -v

# 2) 人工核对：两份 README 结构一致、截图链接有效
```

## 6. 影响范围

仅文档，无代码、无 schema、无接口变化；不签入，待人工确认。
