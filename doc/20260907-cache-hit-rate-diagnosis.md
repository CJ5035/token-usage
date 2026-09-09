# Claude Code 缓存命中率差异诊断

**日期**: 2026-09-07  
**问题**: cc-switch 显示缓存命中率 88.02%，本程序显示 99.54%

## 数据对比

### cc-switch (Claude Code 今日数据)
- Input tokens: 26,894,720
- Cache read tokens: 197,488,128
- Cache write tokens: 42,768,384
- **缓存命中率**: 88.02%

### 本程序抓取数据
- Input tokens: 26.89M (26,890,000)
- Cache read tokens: 197.49M (197,490,000)
- Cache write tokens: 42.77M (42,770,000)
- **缓存命中率**: 99.54%

## 原始数据对比

两边的原始 token 数据基本一致（误差在千位级别，可能是四舍五入）：
- Input: ~26.89M
- Cache read: ~197.49M
- Cache write: ~42.77M

## 缓存命中率计算验证

### 正确公式（CLAUDE.md 口径）
```
hit_rate = cache_read / (cache_read + input)
```

### cc-switch 计算（✓ 正确）
```
197,488,128 / (197,488,128 + 26,894,720) = 197,488,128 / 224,382,848 ≈ 0.8802 = 88.02%
```

### 本程序应该计算（✓ 理论正确）
```
197,490,000 / (197,490,000 + 26,890,000) = 197,490,000 / 224,380,000 ≈ 0.8801 = 88.01%
```

**但实际显示**: 99.54%

## 问题定位

### 数据源分析

根据图片，两边都是 **Claude Code 今日用量数据**。本程序应该从 `claudecode_usage` 表聚合。

### db.py 代码检查

#### `_CC_AGG_COLS` (行 1986-1994)
```sql
COALESCE(SUM(input_tokens + cache_read_tokens + cache_write_tokens), 0) AS total_input_tokens,
COALESCE(SUM(input_tokens), 0) AS uncached_input_tokens,
COALESCE(SUM(cache_read_tokens), 0) AS cache_hit_tokens,
```

这个定义是**正确的**，因为 Claude Code 本地用量中：
- `input_tokens` 和 `cache_read_tokens` 是**互斥**的
- `input_tokens` 表示**未缓存的输入**
- `cache_read_tokens` 表示**缓存命中**

#### 缓存命中率计算（所有聚合函数）
```python
hit = int(row["cache_hit_tokens"] or 0)
miss = int(row["uncached_input_tokens"] or 0)
hit_rate = (hit / (hit + miss) * 100) if (hit + miss) > 0 else 0.0
```

公式本身是**正确的**：
```
hit_rate = cache_read / (cache_read + input)
```

## 推断可能的错误

既然代码逻辑看起来正确，那么问题可能出在：

1. **数据源混淆**: 前端可能显示了错误的数据源（不是 claudecode_usage）
2. **SQL WHERE 条件**: 可能过滤掉了某些数据
3. **数据采集问题**: `claudecode_usage` 表中的数据可能不完整

### 反推错误公式

假设 99.54% 的计算公式是什么？

设缓存命中率 = X / (X + Y) = 0.9954

从图片数据：
- cache_read ≈ 197.49M
- input ≈ 26.89M

如果 X = 197.49M，那么：
```
197.49 / (197.49 + Y) = 0.9954
197.49 = 0.9954 × (197.49 + Y)
197.49 = 196.58 + 0.9954Y
0.91 = 0.9954Y
Y ≈ 0.91M
```

但 0.91M 不对应任何已知数据。

### 另一种可能：分子错误

如果分母正确 (cache_read + input = 224.38M)，那么：
```
X / 224.38 = 0.9954
X ≈ 223.35M
```

这个数值接近 `cache_read + cache_write = 197.49 + 42.77 = 240.26M`（不匹配）

或者 `total_input = input + cache_read + cache_write = 267.15M`（不匹配）

## 下一步排查

需要检查：

1. **前端数据渲染**: `app/web/app.js` 中缓存命中率的显示逻辑
2. **API 响应**: `/api/dashboard` 或类似接口返回的具体数据
3. **数据库实际值**: 直接查询 `claudecode_usage` 表的聚合结果
4. **聚合函数调用**: 确认前端调用的是哪个聚合函数（`totals`? `cc_totals`?）

## 待验证假设

**假设1**: 前端可能混用了不同的聚合字段，比如用了 `total_input_tokens` 作为分母而不是 `cache_hit_tokens + uncached_input_tokens`

**假设2**: 可能存在一个特殊的 Claude Code 聚合函数，使用了不同的计算逻辑

**假设3**: 数据采集时 token 字段映射错误（比如把 cache_read 当成了 total_input）
