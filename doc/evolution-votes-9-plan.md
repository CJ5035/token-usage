# EVOLUTION-9 门禁2 投票记录（计划评审）

## 第 1 轮（2026-09-06）

### 架构师：通过

建议：
1. 测试断言 6 锚函数域（userSwitchTip/userCountTip 在 renderAll/syncTopBar 域、syncFailTip 在 renderQuotaBar 域、「同步失败」硬编码全文件零命中），勿按行号（提取后行号必漂移）。
2. syncI18nTitles 仅 applyLang 内一处（init :2541 经由 applyLang 覆盖，双调用点冗余）。
3. 键数表述：标题"约 9 个"与正文"10 个"不一致；实盘 navStats/navSettings/navAbout 可复用 statsTitle/settingsTitle/aboutTitle，实际新键收敛为 7 个（themeToggle/minimize/close/navHome/navRecords/navAccountsOverview/syncFailTip）——改"约 7-10 个以盘点为准"。
4. applyLang 保留的 loadRecords() 仍是网络请求+隐藏记录容器写穿（同族）——留档备选池，不要求本批。
5. 加"以整段平移实现"封口句（诊断 §4 表述差异封口）。
6. 验收 ⑨ 补 node --check app/web/app.js 语法门。

核实记录：syncTopBar 提取边界（:1498-1510 段内三个局部常量无段外引用，逐行平移安全）；applyLang 替换结构吻合；幂等双写安全；applyCurrency 早退兜底链完整；I18N 盘点（复用 4 键存在、10 新键 grep 零命中）；无计划外改动。

### 产品经理：驳回

阻塞：
1. **验收⑦ 缩水**：诊断 §6 矩阵为"首页 all/单渠道各页签、统计、记录、总览"，计划 ⑦ 仅首页两视角——统计/记录/总览三页缺失，而它们的最终一致从此完全依赖 switchPage 回页重载这一单一兜底机制，正是本计划最高风险行为假设，验收未取证。改法：⑦ 扩为四视角实拍留档（既有实拍会话顺路完成，增量成本近零）。

建议：
2. §1.3 键数统一为 10（与测试第 4 条锚定口径一致）。
3. ① 实拍顺带亮暗各一张（诊断 §6 主题维度）。

核实记录：11 处硬编码/2 处 data-i18n-title/：2270/顶栏写点/applyCurrency 替换点/init null 保护全部与源码吻合。

### 用户体验官：通过

建议：
1. ①④ 实拍各切一次暗色顺带抽查（tooltip 为 OS 渲染与 CSS 主题正交，成本≈0）。
2. ④ 补布局观察留档一句（已核实 .est-badge inline-flex 自适应、「估」→「估算」增宽 ~10px 无挤压；与本就显示 t("estimateBadge") 的其余 4 处徽标统一，消除现存「估」vs「估算」不一致）。
3. syncI18nTitles 单一调用点（同架构师-2）。

附：同族遗漏核查闭合——index.html 无其他漏接线 tooltip；app.js 其余 title= 均为动态数据或已接 t()；trend-hint「30 天」有兜底零可感知窗口；about-sub 品牌化英文双语一致非同族。

### 判定

streak = 0（PM 驳回）。修订 v2 后进入第 2 轮。

## 修订对照表（第 1 轮意见 → 落实情况，v2）

| 上轮意见 | 落实情况 |
|---|---|
| PM-阻塞1：⑦ 四视角 | ✅ §4 ⑦ 扩为"首页 all/单渠道、统计、记录、总览四视角实拍留档" |
| 架构师-1：断言锚函数域 | ✅ §1.4 断言 6 改函数域锚定 |
| 架构师-2 + 体验官-3：单一调用点 | ✅ §1.2-A 改"仅 applyLang 内一处（init 经由 applyLang 覆盖）" |
| 架构师-3 + PM-建议2：键数表述 | ✅ §1.3 改"约 7-10 个，以实施盘点为准（已盘出 3 个可复用：navStats/navSettings/navAbout←statsTitle/settingsTitle/aboutTitle）" |
| 架构师-4：loadRecords 写穿留档 | ✅ §2 不改动清单留档备选池 |
| 架构师-5：整段平移封口 | ✅ §1.2-B 加封口句 |
| 架构师-6：⑨ 补 node --check | ✅ §4 ⑨ 补 |
| PM-建议3 + 体验官-1：亮暗顺带 | ✅ §4 ①④ 补 |
| 体验官-2：④ 布局观察 | ✅ §4 ④ 补观察留档 |

## 第 2 轮（2026-09-06）—— 门禁2 通过轮（三席独立）

### 架构师：通过
建议（实施级留档）：①§1.2-D :473 overview 分派也在块首早退范围（勿按列举逐行对照）②测试第 4 条按实际键集合（7-10）落锚勿硬编码 10 ③提取后 applyLang 不再触达 homeVisible/statsVisible 条件重渲段（:1490-1497 统计页 KPI/图表）——switchPage 兜底可感知窗口≈0，实施留档行为变化口径。
对照表核对：6/6 落实。

### 产品经理：通过
建议：测试第 4 条按"实际键清单（含复用锚）断言 zh/en 存在"，勿硬编码"10 个新键"（与 §1.3 盘点口径一致）。
对照表核对：3/3 落实（阻塞项四视角取证对象经源码核实成立）。

### 用户体验官：通过
建议：④ 留档顺带覆盖英文「Est.」态增宽观察（成本≈0）。
对照表核对：3/3 落实。

### 判定
streak = 2（连续全票，三席独立）→ **门禁2 通过**，计划 v2 定稿，派发 SDD 实施。
