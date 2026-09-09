# EVOLUTION-10 实施计划（v2）：统计页本地用量表格增加表格内横向滚动容器 + DSH 表补 td 防线与 title 补偿

- 日期：2026-09-06 · 第四轮迭代 · 阶段3 · **v2（门禁2 第1轮三席意见吸收版）**
- 输入：`doc/evolution-diagnosis-10.md`（v5，门禁1 通过）+ 门禁2 第1轮三席意见（架构师/PM/体验官均驳回后修订）
- v1 → v2 修订摘要：
  1. **[架构师阻塞]** 补遗漏的第二处 `count("tbl-scroll") == 1` 契约断言改写——`tests/test_i18n_consistency.py:164-165`（与 test_narrow_layout.py:89 互为副本）；执行前以 `grep -rn "tbl-scroll" tests/` 全量盘点自证。
  2. **[PM+体验官阻塞]** 新增 §2.4 CC 表行为变化裁决（"零操作可见 → 容器内横滚 ~66px"显式接受）+ §4.2 CC 验收行。
  3. **[体验官阻塞2，采纳其方案(a)]** DSH 表三处渲染模板补 title 属性（渠道名/模型表 provider/model-cell），消除"截断后全名不可达"缺口；放弃"零 JS"表述，改为"纯模板字符串改动（零逻辑变更）"。
  4. **[架构师建议]** 修正 §2.1 论据（app.js:872/1089 有容器 hidden 切换引用）；DSH 长名验收数值由"~1099px 量级"改为"DSH 渠道表固有列宽（~770px 量级）"；测试改写同步模块 docstring（test_narrow_layout.py:9-11）与函数名（去 exactly_once）；§1 范围表补 dsh-today-note。
  5. **[PM/体验官建议]** §4.2 补 DSH 模型表长名注入走查、851px 三容器滚动条同屏形态确认、title 确认项。

## 1. 目标与范围

**目标**：窄窗口（851~1033px CSS 宽，1366×768 全屏笔记本出厂默认场景）下，统计页本地用量区的表格数字列从"整页横滚 + 隐形滚动条"恢复为"表格内局部滚动可达"；DSH 表获得与 ZCode/CC 表同款的 td 级长名防线，并对新增截断补 title 补偿（全名悬浮可达）。

**范围**（六表两卡三容器，全部在统计页）：

| 容器 | 包含 | 现状 | 本轮改动 |
|---|---|---|---|
| `#zcode-tables`（index.html:125） | ZCode 渠道表+模型表 | 裸容器，td 有防线；app.js:872 引用做 hidden 显隐 | 加 `tbl-scroll` 类 |
| `#dsh-tables`（index.html:139） | DSH 渠道表+模型表+`#dsh-today-note` 口径提示行（index.html:140，hidden 切换，显示时位于两表之前，不影响 `.tbl + .tbl` 兄弟命中）；无 JS 引用（纯静态） | 裸容器，td 无防线 | 加 `tbl-scroll` 类 + td 防线 + 渲染模板 title×3 |
| `#claudecode-tables`（index.html:150） | CC 渠道表+模型表 | 裸容器，td 有防线（复用 zcode-stats 类名）；app.js:1089 引用做 hidden 显隐 | 加 `tbl-scroll` 类 |

**明确不做**（最小化边界，诊断 §9 已界定）：
- report 渠道明细表（index.html:76）已有 .tbl-scroll，不动；
- records 页两表（table-layout:fixed 防线，工作正常），不动；
- 滚动条 thumb 可见性增强（var(--border) 低对比）——本轮不改样式，原因见 §2.5；
- ZCode/CC 表**既有**被截列的 title 补偿——维持现状记候补池（本轮只补 DSH **新增**截断的 title，见 §2.3）；
- min_size 物理像素、overflow-y:overlay 废弃值——候选清单备选池，与本问题解耦。

## 2. 方案设计（形态裁决结论）

### 2.1 主方案：容器级——三个既有容器 div 加 `tbl-scroll` 类（复用先例）

- `.tbl-scroll { overflow-x: auto }`（style.css:292）是 EVOLUTION-8 已验证的先例原语（report 表在用）。
- **关键结构事实**：三卡的两张表本就各自包在一个容器 div 里（#zcode-tables/#dsh-tables/#claudecode-tables，无任何既有 CSS 规则）。给这 3 个 div 加类，即实现"两表共用一个滚动容器"——满足 UX官门禁1建议（避免上下表独立滚动错位割裂），且比逐表包裹少 3 个 DOM 层级。
- **JS 影响评估（v2 修正表述）**：app.js:872/1089 引用 #zcode-tables/#claudecode-tables 仅做 `tables.hidden = true/false` 整体显隐切换（:880/:888/:1097/:1105）；`hidden` → display:none 不参与布局，与容器 `overflow-x:auto` 无冲突——**容器加类零逻辑影响**。本轮对 app.js 的改动仅限 §2.3 的渲染模板 title 属性（纯模板字符串，无逻辑变更）。
- **间距不受影响**：`.zcode-stats .tbl + .tbl { margin-top: 12px }`（style.css:469）是兄弟选择器，两表在容器内仍互为兄弟，规则继续命中；DSH 表间距来自 `.tbl { margin-top: 4px }`（:293），同理。

### 2.2 辅方案 A：DSH 表补 td 防线（一行选择器扩展）

- 现 rule（style.css:470-471）：
  ```css
  /* 渠道/模型名为用户自定义字符串, 超长单元格省略防破版 */
  .zcode-stats .tbl td { max-width: 260px; overflow: hidden; text-overflow: ellipsis; }
  ```
- 改为：`.zcode-stats .tbl td, .dsh-stats .tbl td { max-width: 260px; overflow: hidden; text-overflow: ellipsis; }`
- 行为对齐：DSH 表长名单元格获得与 ZCode/CC 表完全相同的截断行为。
- td 防线（长名单格截断）与容器滚动（固有列宽溢出）职责正交：前者防"表格被长名撑爆"，后者救"数字列被固有列宽挤出视口"，缺一不可。

### 2.3 辅方案 B：DSH 新增截断补 title（体验官方案(a)，采纳）

- **问题**：td 防线使 DSH 长名用户从"横滚可看全名（低可发现但存在）"变为"截断"；且模型表第二列包在 `.model-cell`（flex，app.js:1042 + style.css:303）内，td 的 text-overflow 对 flex 子元素不产生省略号——硬裁且无"被截断"视觉提示。信息可达性净恶化不可接受。
- **方案**：DSH 渲染模板 3 处补 title（全名悬浮），对齐项目内"截断 + title"成对先例（app.js:1476 模型图标 img 即带 title=模型名）：
  - app.js:1033 渠道表首列 td → `<td title="${escapeHtml(p.provider || "")}">`
  - app.js:1041 模型表第一列 td → `<td title="${escapeHtml(m.provider || "")}">`
  - app.js:1042 `.model-cell` span → `<span class="model-cell" title="${escapeHtml(m.model || "")}">`（对齐 ：1476 图标 title 先例）
- ZCode/CC 表的**既有**截断无 title 缺口维持现状记候补池（不在本轮扩散范围；三卡统一补齐属独立改进）。

### 2.4 裁决记录一：CC 表行为变化（PM/体验官阻塞项）

- **现状**：CC 两表（6 列）是实测确认的未触发面——窄窗下末列溢出卡片边缘但仍在视口内**零操作可见**（800px 下 right=773 < 800，.card 无 overflow 不裁切）。
- **修复后**：容器 `overflow-x: auto` 收编该溢出——末列需容器内横滚 ~66px 可达，并出现滚动条。这是本修复对未触发问题用户引入的**唯一行为回退**。
- **接受理由**：① 消除"列内容悬浮在卡片边框之外"的破版观感（溢出到卡片外的内容本就是视觉缺陷）；② 六表形态一致，CC 获得与 ZCode/DSH 同源防线，防御未来 CC 数据列宽增长（模型名变长即进入触发面）；③ 滚动条有表格语境（紧贴表下方），可发现性远高于整页横滚；④ 代价量级小（~66px 一步横滚）。诊断 v3/v5 已声明"六表统一包裹的形态一致性收益独立成立"，本节为显式接受记录。

### 2.5 裁决记录二：为什么不改滚动条样式

- 容器级方案继承 report 先例的滚动条低可见性（thumb var(--border)）。本轮**不改**：① 滚动条随容器出现在表格正下方（有横向滚动语境），可发现性显著优于页面底部的整页滚动条；② 改 thumb 样式须同步改写 test_narrow_layout.py:108-113 回归锚，扩大改动面；③ 可见性增强属独立体验改进，记入候补池（含"溢出提示"方案），不搭车。851px 下三容器滚动条同屏形态以 §4.2 走查截图实证。

## 3. 具体改动清单（预告，执行阶段生成增量 Diff）

### 3.1 `app/web/index.html`（3 行修改）

- :125 `<div id="zcode-tables">` → `<div id="zcode-tables" class="tbl-scroll">`
- :139 `<div id="dsh-tables">` → `<div id="dsh-tables" class="tbl-scroll">`
- :150 `<div id="claudecode-tables">` → `<div id="claudecode-tables" class="tbl-scroll">`

### 3.2 `app/web/style.css`（1 行修改）

- :471 选择器扩展：`.zcode-stats .tbl td` → `.zcode-stats .tbl td, .dsh-stats .tbl td`（注释行 :470 语义不变，不动）

### 3.3 `app/web/app.js`（3 处模板字符串修改，零逻辑变更）

- :1033 DSH 渠道表首列 td 补 `title`（§2.3）；
- :1041 DSH 模型表第一列 td 补 `title`；
- :1042 `.model-cell` span 补 `title`。
- 均为渲染模板字符串内加属性，escapeHtml 沿用既有调用；不触碰任何函数签名/控制流/事件绑定。

### 3.4 测试改写与新增（执行前先 `grep -rn "tbl-scroll" tests/` 全量盘点自证——门禁2 架构师阻塞项要求）

`tests/test_narrow_layout.py`：
- **改写** `test_tbl_scroll_in_html_exactly_once_before_report_table`（:87-92）：`count == 1` 反向断言与现实冲突（改后 count == 4）。改为结构化断言：
  - report 表（`id="report-table"`）仍被 tbl-scroll 包裹（保留原顺序断言精神）；
  - `#zcode-tables`、`#dsh-tables`、`#claudecode-tables` 三个开标签均含 `tbl-scroll` 类；
  - 总数恰为 4（"防扩大"语义反转为"防再漏 + 防乱贴"：新增表格容器必须显式决定防线形态）。
- **同步**模块 docstring（:9-11 "仅出现一次"表述）与函数名（去 `exactly_once`，如 `test_tbl_scroll_wraps_report_and_stats_tables`），防止注释与断言脱节。
- **新增** `test_dsh_tables_td_defense`：style.css 含 `.dsh-stats .tbl td` 防线选择器且带 `max-width: 260px`。
- **新增**（轻量）`test_scroll_containers_only_in_stats_local_cards`：断言 index.html 中 tbl-scroll 的 4 处分别位于 report 表与三个本地用量容器内（防类被误贴到 records 等已有自己防线的表格）。
- 既有 `test_webkit_scrollbar_customization_unchanged`（:108-113）**零改动**（本轮不动滚动条样式，回归锚继续有效）。

`tests/test_i18n_consistency.py`（门禁2 架构师阻塞项）：
- **改写** `test_tbl_scroll_still_wraps_only_channel_table`（:164-165）：`count == 1` → `count == 4`，docstring 注明与 test_narrow_layout 结构化断言的分工（i18n 文件持总数锚、narrow_layout 持定位锚）；同步 :17 模块 docstring 的"tbl-scroll 防扩大锚"表述。

## 4. 测试验证点（重点覆盖用户体验场景）

### 4.1 自动化（统一验证门）

- 全量 `pytest tests/ -q` 通过（基线 459 passed + 本轮新增/改写断言）；
- 改写后的结构化断言在"撤掉任一容器的 tbl-scroll 类"时变红（防退化锚）——执行阶段用临时回退文件自证。

### 4.2 人工/UI 走查（量化基线，来自门禁1交接要求；服务：`.probe/serve_ui.py`）

以 800/851/1033 三档视口宽打开统计页（serve_ui.py + 浏览器 DOM 定量），验收：

| 验收点 | 视口 | 基线（修复前 right，不可见） | 修复后预期 |
|---|---|---|---|
| ZCode 渠道表末列"平均首字延迟" | 851px（1366×768@150% 全屏） | 885 | 容器内滚动到末尾后可见（容器 scrollWidth > clientWidth；页面 #page-stats scrollWidth == clientWidth，**整页横滚消失**） |
| ZCode 模型表末列"平均输出速度" | 1033px（1366×768@125% 全屏） | 1073 | 同上 |
| DSH 模型表末列"平均 tok/s" | 851px | 931 | 同上 |
| CC 两表末列（行为回退验收，§2.4） | 800/851px | 773（零操作可见） | 容器滚动条出现，末列容器内滚动可达（~66px 一步）；**预期变化非缺陷** |
| CC 两表（宽窗回归） | 1280px | — | 容器无滚动条（内容自适应），显示与修复前一致 |
| DSH 长名注入·渠道表首列（102 字符） | 800px | 表格撑至 1177px | 长名单元格被 td 防线截断，容器 scrollWidth 收敛到 DSH 渠道表固有列宽（~770px 量级）且容器内可达；悬浮渠道名 td 出 title 全名 |
| DSH 长名注入·模型表 provider + model-cell（各 102 字符） | 800px | — | 硬裁路径：scrollWidth 同样收敛；model-cell 悬浮出 title=模型全名；无省略号为已知 flex 限制（title 补偿闭环） |
| 三容器滚动条同屏形态 | 851px | — | 亮/暗各一张截图：三条 8px 滚动条紧贴各卡表格下方，视觉噪音可接受（§2.5 实证） |

- 主题覆盖：亮/暗各走查一次（滚动条样式为全局 var(--border)，暗色沿用 dark 值）；
- 回归核对：report 表、records 页表格行为不变；表格 hover 高亮、`.tbl + .tbl` 间距、dsh-today-note 显隐、ZCode/CC 卡 hidden 切换（无数据态）不受影响。

## 5. 回滚方案

- 纯 HTML/CSS/JS 模板字符串/测试改动，无逻辑变更、无后端、无数据迁移：`git checkout -- app/web/index.html app/web/style.css app/web/app.js tests/test_narrow_layout.py tests/test_i18n_consistency.py` 即完整回滚（工作区快照备份由 SDD 快照机制承担）。
- 运行时风险接近零：CSS 仅复用 .tbl-scroll 既有定义与既有选择器形态；app.js 仅模板字符串加属性（escapeHtml 既有调用）。

## 6. SDD 任务拆分（两任务）

- **Task 1**：index.html 三处加类（§3.1）+ style.css 选择器扩展（§3.2）+ app.js 三处 title（§3.3）。
- **Task 2**：test_narrow_layout.py 一改两增 + docstring/函数名同步、test_i18n_consistency.py 断言与 docstring 同步（§3.4）+ 防退化自证（临时移除类→断言变红→恢复）+ `grep -rn "tbl-scroll" tests/` 盘点记录。
- 收尾：全量 pytest + UI 走查（§4.2 量化基线）→ 亮暗截图留档 `.probe/ui-shots-v4/`。

## 7. 交接备忘（给阶段6 进化日志）

- 本轮候选 2/3（EVOLUTION-11 错误恢复入口不对等、EVOLUTION-12 长文本溢出三处）未处理，待本问题闭环后按流水线串行推进；
- 候补池新增：滚动条可见性增强 / 溢出提示；ZCode/CC 表既有截断列的 title 补偿（范围已按本轮裁决收敛为"既有缺口"，DSH 新增截断已在本轮闭环）。
