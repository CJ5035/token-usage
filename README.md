# GoGauge — OpenCode Go 用量仪表盘

<p align="center">
  <img src="assets/GoGauge.ico" width="64" alt="GoGauge">
</p>

<p align="center">
  <b>本地优先的 OpenCode Go 用量统计面板</b>：配额窗口、Token 构成、模型排行、使用记录，打开即见。
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

- **配额窗口实时监控**：滚动 5 小时 / 每周 / 每月，进度条 + 剩余比例 + 重置倒计时
- **用量概览**：缓存命中率 / 命中量 / 总 TOKEN（含缓存命中）/ 请求数 / 费用 / 会话数
- **今日趋势**：24 小时输入 / 输出柱状图
- **用量统计**：Token 构成（输入 / 输出 / 推理 / 缓存读 / 缓存写 / 会话）、模型用量环形图 + 排行、费用/请求/总 TOKEN 三线趋势
- **会话历史**：按会话聚合请求数 / 输入 / 输出 / 推理 / 总 Token / 成本，分页浏览
- **使用记录**：请求级明细分页浏览，支持模型筛选
- **内置 WebView 登录**：独立登录窗口打开官方授权页，自动回填 cookie 与工作区，无需手动复制
- **自动同步**：增量同步（1/5/15/30 分钟可选）+ 同步范围设置（30/60/90/180 天 / 所有）
- **双主题**：亮色 / 深色一键切换；中英双语界面
- **系统托盘**：关闭窗口最小化到托盘；应用图标使用品牌 Logo
- **本地优先**：所有数据保存在本机 SQLite，登录凭据仅用于同步官方接口

## 🖥 快速开始

### 直接使用（Windows）

下载 [Releases](../../releases) 中的 `GoGauge.exe`（单文件，无需安装）：

1. 双击运行，欢迎页点击「立即登录」弹出官方授权窗口
2. 完成登录后自动进入面板并同步用量数据
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

- **数据来源**：opencode.ai 工作区用量接口（`/_server` server-fn）+ 配额页 HTML 解析
- **总 TOKEN** = 输入（含缓存命中）+ 输出 + 推理
- **缓存命中率** = 命中 /（命中 + 未命中）
- **费用**：USD 原始值，人民币按 open.er-api.com 实时汇率换算（24h 缓存）

### Codex 本地数据

- **数据来源**：本机 Codex 会话日志，目录优先级 `GOUSAGE_CODEX_HOME` > `ZBAR_CODEX_HOME` > `~/.codex`（读取其 `sessions` 目录）；未登录远程账号也可查看
- **采集内容**：仅 Token 用量事件（模型 / provider / 时间），不读取、不保存任何对话内容
- **全历史口径**："全历史"指本机可读的会话日志与本地镜像数据，并非云端账户的累计用量
- **provider 与速度**：provider 取自日志记录；速度仅当日志含明确耗时字段时统计，缺失时显示 `—`（不做估算）
- **数据口径**：Codex 用量进入统计页独立区块与全渠道报表；使用记录 / 会话页明细在当前阶段不含 Codex（统一来源筛选属后续阶段）
- **同步间隔**：Codex 增量导入复用设置页既有的自动同步间隔控件，设置页无 Codex 专用控件
- **保留策略**：远程「同步范围」的保留天数仅作用于远程账号历史，不会删除 Codex 本地镜像

## 🔒 隐私

- 登录 cookie 仅保存在本机，绝不写入日志、绝不上传
- 用量数据全部本地存储，应用不含任何遥测

## 🛠 技术栈

Python · pywebview (WebView2) · SQLite · Chart.js · pystray

## 📬 联系

- GitHub：[yphyphyph/opencode-go-gauge](https://github.com/yphyphyph/opencode-go-gauge)
- CSDN：[Ying_ph](https://blog.csdn.net/Ying_ph)

## 📄 License

[MIT](LICENSE) © GoGauge
