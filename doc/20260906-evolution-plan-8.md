# EVOLUTION-8 实施计划：窄窗排版错乱三连修复

- **问题编号**：问题 8（第三轮候选 #2）
- **依据**：`doc/evolution-diagnosis-8.md` v3（门禁1 三轮通过，streak=2）
- **版本**：v2（门禁2 第 1 轮全票后吸收 7 条建议：margin 并入既有块、断言锚定细节、验收矩阵约定、滚动条继承说明、设置页核对进条目、667 en 组合留档、结构重排；对照表见 `doc/evolution-votes-8-plan.md`）
- **改动原则**：最小化——三处缺陷各一个 CSS/HTML 级修复点；不动 JS（零 app.js 改动）、不动 db/server、不动 records 页既有保护

## 1. 改动文件与内容

### 1.1 `app/web/style.css`（约 +5 行声明）

**A. pill/标题（R1）**——全部**并入既有规则块**（架构师 R2：不新增独立规则块，保持同文件单块一致性）：

- `.pill`（:92 块内）加：`white-space: nowrap;`
- `.pill-row`（:93 块内）加：`flex-wrap: wrap;`
- `.ph`（:194 块内）加：`flex-wrap: wrap;`
- `.ph-right`（**:196 既有块**内）加：`margin-left: auto;`

机制（诊断 v3 §5.1）：margin-left:auto 宽屏吸收自由空间保持现状右对齐（css-flexbox §8.1：auto margin 优先于 justify-content 分配）；换行后 .ph-right 单 item 行推至右缘。`.ph-right` 复用点影响面（已核实无回归）：index.html:70（#report-all 下 seg 容器，block 流 margin 解析为 0）、:101（统计页 .ph，同受益）、:171（records card-h，space-between 下位置不变）。

**B. 明细表横向滚动（R2，方案 b）**——新增规则（表格分区 :292 附近）：

```css
.tbl-scroll { overflow-x: auto; }
```

- **仅包裹首页渠道明细表一处**（勿扩大到 records 两表——已有 fixed+ellipsis 保护，双滚动语义混淆）。
- 取舍留档（PM 席）：不选缩字号（伤 667px 可读性）、不选减列（丢列语义）；横向滚动是桌面表格惯例；备选「窄宽度隐藏次要列」仅在滚动条观感不佳时启用。
- 滚动条观感说明（体验官 R2）：项目已有全局 `::-webkit-scrollbar` 定制（style.css:155-158，8px、thumb=var(--border)、hover=--text3），.tbl-scroll 滚动条自动继承该样式——暗色 ⑥ 核对按继承样式预期执行，非系统原生观感。

**C. two-col 断点（R3）**——既有 `@media (max-width: 1000px)` 块（:414-416）内补一行：

```css
#page-stats .two-col { grid-template-columns: 1fr; }
```

- 同特异性（0,1,1,0）源序在后获胜；>1000px 时 media 失效 :270 生效，双向正确。:410/:473 两个 @media 块**不需要**补齐（无 ID 前缀竞争规则）。

### 1.2 `app/web/index.html`（约 +2 行）

渠道明细表（:76）包滚动容器：

```html
<div class="card"><div class="card-h"><h3 data-i18n="chTableTitle">渠道明细</h3></div>
  <div class="tbl-scroll"><table class="tbl">…（原表内容零变化）…</table></div>
</div>
```

### 1.3 `tests/test_narrow_layout.py`（新增，约 60 行，源码静态断言，沿用项目先例）

1. **块级锚定断言**（架构师 R2：防误匹配）：`.pill` 规则块（区别于 .pill.small :95 / .pill.active :94 / .chip :99 既有 nowrap / .tbl th/td :293-294 既有 nowrap）含 `white-space: nowrap`；`.pill-row` 块含 `flex-wrap: wrap`；`.ph` 块含 `flex-wrap: wrap`；`.ph-right` 块（:196）含 `margin-left: auto`；存在 `.tbl-scroll { overflow-x: auto }`；`@media (max-width: 1000px)` 块（**锚定 :414 目标块**——文件中另有 :322 一个 1000px 块含 .ov-today，勿误锚）内存在 `#page-stats .two-col { grid-template-columns: 1fr }`。
2. **防扩大强断言**：`tbl-scroll` 在 index.html 全文件**仅出现一次**（出现位置在 `id="report-table"` 之前）。
3. **回归锚**：:270 `#page-stats .two-col { grid-template-columns: 1fr 1.6fr; }` 原规则未变；:133-134 records 保护规则未变。

## 2. 不改动清单

- app.js / server.py / db.py（零 JS/后端改动）
- records 页表格及其 :133-134 保护、:127-128 行高契约
- :410/:473 两个 @media 块、.tc-grid/.d6-grid/.kpi-row 规则
- ::-webkit-scrollbar 既有定制（:155-158，零改动）
- .ub-meta（备选池跟踪）、.wb-cell、其他多列网格
- 暗色主题 token（滚动条观感仅核对，不新增样式）

## 3. 实施备注

1. `.pill`/`.pill-row`/`.ph`/`.ph-right` 全部是往**既有规则块内加声明**，不新增规则块（.tbl-scroll 除外）。
2. margin-left:auto 与 justify-content:space-between 并存兼容（auto margin 优先分配）。
3. 明细表包裹时 `<table class="tbl">` 标签与属性逐字保留，仅外层加 div。
4. **667px 英文档组合留档**（架构师 R2）：英文 pill 文案下 #channel-tabs+#home-pills ≈638px > 583px 可用宽，.ph-right（flex-shrink 默认 1）会收缩并触发 .pill-row 组内换行、铺满整行——此档下"右对齐"（验收④）无意义而非失败；如实拍观感不佳，备选给 .ph-right 加 `flex-wrap: wrap`（两 pill-row 纵排），当前不实施。
5. `.tbl-scroll` 命名对齐项目连字符风格；不加暗色滚动条定制（先核对继承的 ::-webkit-scrollbar 样式观感，不佳再备选启用）。

## 4. 验收清单（诊断 v3 §5.4 可判定条目，显式编号）

| # | 条目 | 方式 |
|---|---|---|
| ① | 667/800px 下每个 pill 文字自身单行（无竖排） | 实拍 + DOM（pill 高 ≈28px） |
| ② | 换行仅发生在 pill 边界（组内或组间均可），不发生在 pill 文字内部 | 实拍 |
| ③ | 标题「用量统计总览」单行 | 实拍 + DOM（title 行盒高 ≈27px，18px×line-height 1.5） |
| ④ | 换行后 pill 组仍右对齐（基线实拍对照 1280px 档=截图 03，保留并排证据） | 实拍对照 |
| ⑤ | 明细表 800px 可横向滚动至「数据自」完整可见；**滚动条可见且可拖拽**（继承 :155-158 全局定制，浅/暗两主题常显） | 实拍 + DOM（scrollWidth 对比） |
| ⑥ | 暗色主题滚动条与卡片对比度核对（按继承样式预期） | 实拍 |
| ⑦ | 统计页 two-col 800px 单列，与首页同宽并排截图一致性回归锚 | 实拍 |
| ⑧ | 800px 英文界面档验收；**执行矩阵约定：英文档仅亮色执行①-⑤⑦（⑥ 暗色仅中文档执行）** | 实拍 |
| ⑨ | 667×453 极端矮高：页头垂直成本与首屏观感；**顺带切英文界面补一张快照；顺带核对设置页 pill-row 无溢出（667px）** | 实拍 |
| ⑩ | 1000px+ 布局零变化（对照截图 03 与设置/记录页现状） | 实拍对照 |
| ⑪ | `.ph-right` 另 3 处复用点（:70/:101/:171）无视觉回归 | 实拍（统计页/记录页） |
| ⑫ | 源码静态断言（1.3） | pytest |

## 5. 回滚方案

- git 单提交（信息 `product-evolution: 问题8 窄窗排版三连修复`），异常 `git revert <commit>`。
- 改动 2 个源文件 + 1 个新测试文件，无逻辑变更，回滚无残留。

## 6. 风险与缓解

| 风险 | 缓解 |
|---|---|
| .pill nowrap 全局波及（顶栏 .pill.small/设置页 5 组 pill-row） | 已核实 667px 不溢出；验收 ⑧⑨ 覆盖（⑨ 明确含设置页核对） |
| .ph-right margin 对 3 处复用点的连带 | 已静态推演无回归；验收 ⑪ 实拍核对 |
| table 包 wrapper 后 .tbl width:100% 基准变化 | 已核实等价（.card 无 padding，tbl-scroll block width:auto 内容宽等于原内容宽，margin-top 在 BFC 内不外塌）；验收 ⑤⑩ 覆盖 |
| two-col 折叠后统计页图表高度 | chart-box min-height 已有 + app.js:2509-2510 已有 250ms 防抖 chart.resize()（可见页），既有机制共用；验收 ⑦ 实拍确认 |
| 667px 英文档 .ph-right 收缩 | §3.4 已留档（该档④无意义属预期）；备选方案已记录 |
