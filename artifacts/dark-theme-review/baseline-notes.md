# D1 深色基准图采集记录（Task 1）

- 采集日期：2026-09-10（凌晨，应用内时间显示 2026-09-10 00:0x）
- 代码基线：仓库 HEAD `8e9fd63` + 工作区 4 处仓库地址改动（README/README_en/updater/index.html，与本主题无关）；应用源码未做任何主题改动
- 采集方式：UIA 自动化点击（artifacts/dark-theme-review/uia_click.ps1）+ 抓屏脚本（capture_window.py, PowerShell CopyFromScreen）
- 数据来源：正式数据（D:/绿色版/GoGauge/data/gousage.db，2 账号 / 658 条记录，integrity ok）复制到开发环境 data/；开发环境原 18.2M 旧库备份为 data/gousage.db.dev-backup-20260909
- 系统环境：Windows 主屏 2560×1600，系统 DPI 144（150% 缩放）；截图为窗口区域物理像素

## 窗口尺寸说明

- "1280x840" 系列实际窗口为 1920×1260 物理像素 = 1280×840 逻辑像素（150% DPI）
- "1000x680" 系列实际窗口为 1500×1020 物理像素 = 1000×680 逻辑像素（最小窗口）

## 产物清单（主题 = 深色）

| 文件 | 页面/状态 | 备注 |
|---|---|---|
| baseline-home-all-1280x840.png | 首页·全部渠道·今天 | 切深色后首帧 |
| baseline-home-zcode-1280x840.png | 首页·zcode 单渠道 | 配额卡/KPI/24h 趋势 |
| baseline-stats-1280x840.png | 统计页 | 4 KPI + Token 构成 + 模型环 + 趋势线 |
| baseline-records-1280x840.png | 使用记录 | 会话用量 + 明细两张表 |
| baseline-settings-1280x840.png | 设置页 | 账户列表/同步设置/主题/面板开关 |
| baseline-about-1280x840.png | 关于页 | |
| baseline-user-menu-1280x840.png | 用户菜单展开 | 背景为关于页；⚠ 顶栏与菜单显示完整账号 UUID（账号标识，非密钥） |
| baseline-modal-1280x840.png | 确认弹框 | "立即全量同步"确认框，已点取消关闭，未执行全量同步 |
| baseline-toast-1280x840.png | toast | 切换账号触发的"已切换账号"；截图后已切回原账号 f8d265c9 |
| baseline-overview-1280x840.png | 账户总览 | 采集需临时开启"账户总览面板"开关，采集后已还原为关 |
| baseline-home-zcode-1000x680.png | 首页·zcode 单渠道（最小窗口） | zcode 页签保持选中态，故小窗口样本为单渠道首页 |
| baseline-stats-1000x680.png | 统计页（最小窗口） | 窄窗布局无裁切 |

## 状态与偏差记录

- 主题切换通过顶栏 ◐ 按钮完成（当前代码仅写 localStorage，无持久化——这正是本轮要修的链路）
- 欢迎页未采集：两个账号均有有效登录态，应用直接进入面板（欢迎页样本留待 D4 矩阵用未登录环境补）
- 同步过程 toast 未捕获（完成时机不可控），改用切换账号 toast；同步中指示条会使顶栏按钮整体左移（布局动态性记录在案）
- "账户总览面板"设置还原后为 False（原值为 None，行为等价：面板关闭）
- 账号切换会真实调用同步（正常应用行为），活跃账号已还原为 f8d265c9-9751-4ac3-883d-a5471d55b547
- 语言为中文；英文界面样本属 D4 桌面矩阵范围，未在本次基线采集
