# GoGauge — 多渠道 AI 编码用量仪表盘

<p align="center">
  <img src="assets/GoGauge.ico" width="64" alt="GoGauge">
</p>

<p align="center">
  <b>本地优先的多渠道 AI 编码用量面板</b>：聚合 OpenCode Go / BAI / CommandCode 云端账号，汇总本机 ZCode / Claude Code / Codex / DSH 会话用量。配额窗口、Token 构成、模型排行、使用记录，打开即见。
</p>

<p align="center">
  <a href="./README_en.md">🌐 English</a>
</p>

---

## 📸 截图

| 主页（亮色） | 主页（暗色） |
|:---:|:---:|
| ![Home Light](assets/screenshots/home-light.png) | ![Home Dark](assets/screenshots/home-dark.png) |

| 用量统计 | 使用记录 |
|:---:|:---:|
| ![Stats](assets/screenshots/stats.png) | ![Records](assets/screenshots/records.png) |

| 设置 | 登录 | 关于 |
|:---:|:---:|:---:|
| ![Settings](assets/screenshots/settings.png) | ![Login](assets/screenshots/login.png) | ![About](assets/screenshots/about.png) |

---

## ✨ 功能

- **7 大数据源聚合**
  - 云端账号（内置 WebView 登录，自动同步）：OpenCode Go · BAI (chat.b.ai) · CommandCode (commandcode.ai)
  - 本机 CLI / 客户端（免登录，只读本地数据）：ZCode (GLM Coding Plan) · Claude Code · Codex · DSH
- **首页全渠道报表**：各渠道配额窗口、分渠道消耗趋势、渠道占比环形图、渠道明细表；也可切到单渠道视图查看该渠道专属配额与账期汇总
- **配额窗口监控**：OpenCode 5 小时 / 每周 / 每月、CommandCode 5 小时 / 每周 / 月度积分、GLM Coding Plan 5 小时 / 每周 / MCP 月度，进度条 + 剩余比例 + 重置倒计时
- **用量统计（数据源分层）**：数据源占比条（点击色块展开对应数据源）、Token 构成（输入 / 输出 / 推理 / 缓存读 / 缓存写 / 会话）、模型用量环形图 + 排行、全渠道用量趋势、单数据源明细面板
- **使用记录**：会话用量 + 请求级明细统一来源筛选（含 Codex），支持来源 / 模型筛选与分页浏览
- **账户总览**：多账户聚合视图 + 7 日费用趋势对比（设置页可开启）
- **多账号管理**：添加 / 重新登录 / 切换账号，登录窗口自动回填 cookie 与工作区，无需手动复制
- **自动同步**：云端渠道增量同步（1/5/15/30 分钟可选）+ 同步范围（30/60/90/180 天 / 所有）；本机渠道启动时自动增量导入
- **费用与汇率**：USD 原始费用，默认货币 ¥ CNY / $ USD 一键切换，人民币按 open.er-api.com 实时汇率换算（24h 缓存）
- **双主题双语**：亮色 / 深色一键切换；中英双语界面
- **桌面体验**：无边框窗口 + 系统托盘（关闭最小化到托盘）+ 单实例守卫 + GitHub Releases 更新检查
- **本地优先**：所有数据保存在本机 SQLite，登录凭据仅用于同步官方接口

## 🖥 快速开始

### 直接使用（Windows）

下载 [Releases](../../releases) 中的 `GoGauge.exe`（单文件，无需安装）：

1. 双击运行，欢迎页点击「立即登录」弹出官方授权窗口
2. 完成登录后自动进入面板并同步用量数据；本机渠道（ZCode / Claude Code / Codex / DSH）无需登录，自动读取本机数据
3. 数据保存在 exe 同目录 `data\` 文件夹

> 需要 Windows 10/11（自带 WebView2 Runtime）。关闭窗口会最小化到系统托盘。

### 源码运行

```bash
pip install -r requirements.txt
python entry.py
```

### 打包

```bash
build.bat
```

输出 `dist\GoGauge.exe`（约 38 MB，--noconsole 无黑窗，含 logo 图标与托盘支持）。

## 📊 数据说明

### 统一口径

- **总 TOKEN** = 输入（含缓存命中）+ 输出 + 推理
- **缓存命中率** = 命中 /（命中 + 未命中）
- **费用**：USD 原始值。OpenCode / CommandCode 由服务端返回；BAI / ZCode / Claude Code 按本地模型定价表估算；Codex 日志不含费用，暂不统计。人民币按 open.er-api.com 实时汇率换算（24h 缓存）
- **速度**：仅当日志含明确耗时字段时统计，缺失时显示 `—`（不做估算）

### 分渠道数据来源

| 渠道 | 类型 | 数据来源 |
|---|---|---|
| OpenCode Go | 云端（登录） | opencode.ai 配额页 HTML 解析 + `/_server` server-fn 用量接口 |
| BAI | 云端（登录） | chat.b.ai trpc 接口（积分余额 / 月度汇总 / 用量明细） |
| CommandCode | 云端（登录） | api.commandcode.ai 内部接口（配额 / 订阅 / 用量明细） |
| ZCode | 本机（免登录） | `~/.zcode/v2` 凭证查询 GLM 开放平台额度 + 本地用量库只读采集（支持 dataBaseDir 迁移目录） |
| Claude Code | 本机（免登录） | `~/.claude/projects` 会话 JSONL（支持 `CLAUDE_CONFIG_DIR` 覆盖），只计 assistant 行 |
| Codex | 本机（免登录） | `GOUSAGE_CODEX_HOME` > `ZBAR_CODEX_HOME` > `~/.codex` 的 `sessions` rollout 日志 |
| DSH | 本机（免登录） | `~/.dsh/sessions` zstd 会话日志（并入全渠道报表与统计页） |

### 本机渠道说明

- **采集内容**：仅读取 Token 用量相关事件（模型 / provider / 时间 / token 数），不读取、不保存任何对话内容
- **"全历史"口径**：指本机可读的会话日志与本地镜像数据，并非云端账户的累计用量
- **保留策略**：云端「同步范围」的保留天数仅作用于远程账号历史，不会删除本机镜像数据
- **同步控制**：本机渠道增量导入复用设置页既有的自动同步间隔控件，启动时自动预热导入

## 🔒 隐私

- 登录 cookie 仅保存在本机，绝不写入日志、绝不上传
- 本机渠道只读访问本地日志与用量库，绝不修改
- 用量数据全部本地存储，应用不含任何遥测

## 🛠 技术栈

Python · pywebview (WebView2) · SQLite · Chart.js · pystray · zstandard

## 📬 联系

- GitHub：[yphyphyph/opencode-go-gauge](https://github.com/yphyphyph/opencode-go-gauge)
- CSDN：[Ying_ph](https://blog.csdn.net/Ying_ph)

## 📄 License

[MIT](LICENSE) © GoGauge
