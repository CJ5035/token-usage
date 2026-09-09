# 缓存命中率修复方案

**日期**: 2026-09-07  
**问题**: 多个聚合函数缺少 `hit_rate` 字段，导致前端显示异常
**状态**: ✅ 可立即执行

## 问题总结

用户报告缓存命中率显示不一致：
- cc-switch: 88.02% ✓
- 本程序: 99.54% ✗

经代码审查发现：**多个聚合函数缺少 `hit_rate` 字段**。

## 根本原因

`db.py` 中以下函数**没有计算和返回 `hit_rate` 字段**：

| 函数 | 行号 | 状态 |
|------|------|------|
| `claudecode_totals()` | 2158-2175 | ❌ 缺少 |
| `claudecode_daily()` | 2178-2206 | ❌ 缺少 |
| `claudecode_channel_stats()` | 2209-2239 | ❌ 缺少 |
| `claudecode_model_stats()` | 2242-2270 | ❌ 缺少 |
| `zcode_totals()` | 1834-1851 | ❌ 缺少 |
| `zcode_daily()` | 1854-1883 | ❌ 缺少 |
| `zcode_provider_stats()` | 1886-1923 | ❌ 缺少 |
| `zcode_model_stats()` | 1926-1971 | ✓ 有 |
| `totals()` | 1570-1611 | ✓ 有 |
| `model_stats()` | 1446-1490 | ✓ 有 |
| `daily_stats()` | 1493-1535 | ✓ 有 |

前端代码（app.js 行1431）期望 `totals.hit_rate` 存在并直接调用 `.toFixed(1)`：

```javascript
{ cls: "c-green", l: t("hitRate"), v: totals.hit_rate.toFixed(1) + "%", ... }
```

当 `hit_rate` 字段缺失时，会导致前端异常。

## 修复方案

为所有缺少 `hit_rate` 的函数添加计算逻辑，与 `db.totals()` 保持一致。

### 计算公式

根据 CLAUDE.md 行48 口径约定：

```python
hit = int(row["cache_hit_tokens"] or 0)
miss = int(row["uncached_input_tokens"] or 0)
hit_rate = (hit / (hit + miss) * 100) if (hit + miss) > 0 else 0.0
```

### 修改清单

#### 1. `claudecode_totals()` (行2158-2175)

**修改前**：
```python
def claudecode_totals(period: str = "30d") -> dict[str, Any]:
    # ... SQL 查询 ...
    return {
        "request_count": int(row["request_count"]),
        "total_input_tokens": int(row["total_input_tokens"]),
        "uncached_input_tokens": int(row["uncached_input_tokens"]),
        "cache_hit_tokens": int(row["cache_hit_tokens"]),
        "cache_write_tokens": int(row["cache_write_tokens"]),
        "total_output_tokens": int(row["total_output_tokens"]),
        "total_tokens": int(row["total_tokens"]),
        "total_cost_usd": _cc_cost_usd(row),
        **_cc_speed_dict(row),
    }
```

**修改后**：
```python
def claudecode_totals(period: str = "30d") -> dict[str, Any]:
    # ... SQL 查询 ...
    hit = int(row["cache_hit_tokens"] or 0)
    miss = int(row["uncached_input_tokens"] or 0)
    hit_rate = (hit / (hit + miss) * 100) if (hit + miss) > 0 else 0.0
    return {
        "request_count": int(row["request_count"]),
        "total_input_tokens": int(row["total_input_tokens"]),
        "uncached_input_tokens": miss,
        "cache_hit_tokens": hit,
        "cache_write_tokens": int(row["cache_write_tokens"]),
        "total_output_tokens": int(row["total_output_tokens"]),
        "total_tokens": int(row["total_tokens"]),
        "total_cost_usd": _cc_cost_usd(row),
        "hit_rate": round(hit_rate, 2),
        **_cc_speed_dict(row),
    }
```

#### 2. `claudecode_daily()` (行2178-2206)

在 return 的字典中添加：
```python
"hit_rate": round((int(r["cache_hit_tokens"] or 0) / (int(r["cache_hit_tokens"] or 0) + int(r["uncached_input_tokens"] or 0)) * 100) 
            if (int(r["cache_hit_tokens"] or 0) + int(r["uncached_input_tokens"] or 0)) > 0 else 0.0, 2),
```

或者提前计算：
```python
for r in rows:
    hit = int(r["cache_hit_tokens"] or 0)
    miss = int(r["uncached_input_tokens"] or 0)
    hit_rate = (hit / (hit + miss) * 100) if (hit + miss) > 0 else 0.0
    result.append({
        # ... 现有字段 ...
        "hit_rate": round(hit_rate, 2),
    })
```

#### 3. `claudecode_channel_stats()` 和 `claudecode_model_stats()`

类似 `claudecode_daily()`，在列表推导式中计算 `hit_rate`。

#### 4. `zcode_totals()` (行1834-1851)

类似 `claudecode_totals()`，添加 `hit_rate` 计算。

#### 5. `zcode_daily()` (行1854-1883)

类似 `claudecode_daily()`，在返回字典中添加 `hit_rate`。

#### 6. `zcode_provider_stats()` (行1886-1923)

类似 `claudecode_channel_stats()`，在列表推导式中计算 `hit_rate`。

## 实施步骤

1. ✅ 创建实施文档（本文档）
2. ⏳ 修改 `app/db.py` 的 7 个函数
3. ⏳ 编译测试
4. ⏳ 验证修复效果

## 验证方法

修复后，检查以下接口的响应：

1. `/api/claudecode/summary?range=today` 
   - `totals.hit_rate` 应该存在且为合理值（0-100）
   
2. `/api/zcode/summary?range=today`
   - `totals.hit_rate` 应该存在且为合理值（0-100）

3. 统计页显示的缓存命中率应该与 cc-switch 一致或接近

## 风险评估

- **影响范围**: 仅影响聚合统计数据的返回值
- **向后兼容**: 新增字段不影响现有功能
- **回滚方案**: 如有问题可立即回滚代码
- **测试需求**: 编译通过 + 接口响应验证

## 预期效果

修复后：
- 所有聚合函数返回一致的数据结构
- 前端不再因缺少字段而报错
- 缓存命中率显示正确

如果修复后仍显示 99.54%，说明问题在其他地方（数据采集 / 前端计算），需要进一步诊断。
