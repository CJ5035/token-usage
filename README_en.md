# GoGauge — Multi-Channel AI Coding Usage Dashboard

<p align="center">
  <img src="assets/GoGauge.ico" width="64" alt="GoGauge">
</p>

<p align="center">
  <b>A local-first usage dashboard for AI coding tools</b>: aggregates OpenCode Go / BAI / CommandCode cloud accounts and local ZCode / Claude Code / Codex / DSH session usage. Quota windows, token breakdown, model ranking and usage records — all in one place.
</p>

<p align="center">
  <a href="./README.md">🇨🇳 中文</a>
</p>

---

## 📸 Screenshots

| Home (Light) | Home (Dark) |
|:---:|:---:|
| ![Home Light](assets/screenshots/home-light.png) | ![Home Dark](assets/screenshots/home-dark.png) |

| Stats | Records |
|:---:|:---:|
| ![Stats](assets/screenshots/stats.png) | ![Records](assets/screenshots/records.png) |

| Settings | Login | About |
|:---:|:---:|:---:|
| ![Settings](assets/screenshots/settings.png) | ![Login](assets/screenshots/login.png) | ![About](assets/screenshots/about.png) |

---

## ✨ Features

- **7 data sources in one place**
  - Cloud accounts (built-in WebView login, auto sync): OpenCode Go · BAI (chat.b.ai) · CommandCode (commandcode.ai)
  - Local CLIs / clients (no login needed, read-only): ZCode (GLM Coding Plan) · Claude Code · Codex · DSH
- **All-channel report on the home page**: per-channel quota windows, stacked consumption trend, channel share donut, channel detail table; a single-channel view is also available with channel-specific quota and billing summary
- **Quota monitoring**: OpenCode 5h / weekly / monthly, CommandCode 5h / weekly / monthly credits, GLM Coding Plan 5h / weekly / MCP monthly — progress bars, remaining % and reset countdown
- **Usage stats (layered by source)**: source share bar (click a block to expand its source), token breakdown (input / output / reasoning / cache read / cache write / sessions), model usage donut + ranking, all-channel trend, per-source detail panels
- **Usage records**: session usage + request-level detail with unified source filtering (Codex included), source / model filters and pagination
- **Account overview**: multi-account aggregate view + 7-day cost trend comparison (toggle in Settings)
- **Multi-account management**: add / re-login / switch accounts; the login window auto-fills cookie & workspace — no manual copy-paste
- **Auto sync**: cloud channels incremental sync (1/5/15/30 min) + sync range (30/60/90/180 days / All); local channels import incrementally on startup
- **Cost & FX**: raw USD cost, ¥ CNY / $ USD default currency toggle, CNY converted via open.er-api.com live rate (24h cache)
- **Dual themes & bilingual**: light / dark toggle; UI in 中文 / English
- **Desktop experience**: frameless window + system tray (close minimizes to tray) + single-instance guard + GitHub Releases update check
- **Local-first**: all data stays in local SQLite; credentials are only used to sync official APIs

## 🖥 Quick Start

### Binary (Windows)

Download `GoGauge.exe` from [Releases](../../releases) (single file, no install):

1. Double-click to run, click "Login Now" on the welcome page — an official auth window pops up
2. After login, the dashboard loads and usage data syncs automatically; local sources (ZCode / Claude Code / Codex / DSH) need no login and are read from your machine automatically
3. Data is stored in the `data\` folder next to the exe

> Requires Windows 10/11 (WebView2 Runtime built-in). Closing the window minimizes to the system tray.

### From Source

```bash
pip install -r requirements.txt
python entry.py
```

### Build

```bash
build.bat
```

Output: `dist\GoGauge.exe` (~38 MB, --noconsole, logo icon and tray support included).

## 📊 Data Notes

### Common Definitions

- **Total tokens** = input (incl. cache hits) + output + reasoning
- **Cache hit rate** = hits / (hits + misses)
- **Cost**: raw USD. OpenCode / CommandCode costs come from the server; BAI / ZCode / Claude Code are estimated with a local model pricing table; Codex logs contain no cost data and are not costed. CNY converted via open.er-api.com live FX rate (24h cache)
- **Speed**: computed only when logs contain explicit duration fields, otherwise shown as `—` (no estimation)

### Per-Channel Data Sources

| Channel | Type | Data source |
|---|---|---|
| OpenCode Go | Cloud (login) | opencode.ai quota page HTML parsing + `/_server` server-fn usage API |
| BAI | Cloud (login) | chat.b.ai trpc API (points balance / monthly summary / usage records) |
| CommandCode | Cloud (login) | api.commandcode.ai internal API (quota / subscription / usage records) |
| ZCode | Local (no login) | `~/.zcode/v2` credentials query GLM platform quota + read-only local usage db (dataBaseDir migration supported) |
| Claude Code | Local (no login) | `~/.claude/projects` session JSONL (override via `CLAUDE_CONFIG_DIR`), assistant lines only |
| Codex | Local (no login) | `GOUSAGE_CODEX_HOME` > `ZBAR_CODEX_HOME` > `~/.codex` `sessions` rollout logs |
| DSH | Local (no login) | `~/.dsh/sessions` zstd session logs (merged into all-channel reports and the stats page) |

### Local Source Notes

- **Collected content**: token usage events only (model / provider / time / token counts) — conversation content is never read or stored
- **"Full history"**: means locally readable session logs and the local mirror, not a cumulative cloud-account total
- **Retention**: the cloud sync range (retention days) only trims remote account history and never deletes local mirrors
- **Sync control**: local incremental import reuses the existing auto-sync interval control; imports warm up automatically on startup

## 🔒 Privacy

- Login cookies stay on your machine only — never logged, never uploaded
- Local sources access your logs and usage db read-only — nothing is modified
- Usage data is stored entirely locally; the app contains no telemetry

## 🛠 Tech Stack

Python · pywebview (WebView2) · SQLite · Chart.js · pystray · zstandard

## 📬 Contact

- GitHub: [yphyphyph/opencode-go-gauge](https://github.com/yphyphyph/opencode-go-gauge)
- CSDN: [Ying_ph](https://blog.csdn.net/Ying_ph)

## 📄 License

[MIT](LICENSE) © GoGauge
