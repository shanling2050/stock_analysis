# l-stock Report Template

Default `run` output is a self-contained HTML report:

```text
reports/YYYY-MM-DD-HHMM.html
cache/run_logs/YYYY-MM-DD-HHMM-snapshot.json
```

HTML is the primary reading format. PDF and Markdown are on-demand exports:

```text
reports/output/YYYY-MM-DD-HHMM.pdf
reports/output/YYYY-MM-DD-HHMM.md
reports/output/YYYY-MM-DD-HHMM-assets/
```

正式 HTML 报告只在 gate 为 PASS 或 WARN 时生成。同名文件已存在时追加 `-02`、`-03` 后缀。报告由 `lstock_report.py` 根据快照渲染。不要在数据闸门 BLOCK 时手写正式买卖建议。

## HTML 主报告结构

主报告按固定顺序展示：

1. 今日剧本
2. 市场温度计
3. 行动矩阵
4. 持仓诊断
5. 关注池技术跟踪
6. 数据附录

HTML must include:

- Header with report time, data gate status, and export controls.
- Desktop side navigation using the same six-section order.
- 今日剧本：给出当日结论、持仓边界、关注池边界和风险边界。
- 市场温度计：用指标卡解释指数结构、情绪温度、涨停 / 炸板和主线资金。
- 行动矩阵：合并持仓与关注池的当日动作，关注池只显示技术跟踪。
- 持仓诊断：section 本身可折叠，默认展开；每只持仓一张 K-line 图卡。
- 关注池技术跟踪：section 本身可折叠，默认收起；每只关注股一张 K-line 图卡。
- 数据附录：默认收起，保留 gate、market、emotion、fallback 和图表输入摘要。
- Embedded K-line PNG data URIs in HTML. Do not reference external assets.
- Print CSS for PDF export, with navigation/export controls hidden and chart cards guarded with `break-inside: avoid`.
- PDF/print export must open every collapsible section before printing so default-collapsed 关注池技术跟踪 and 数据附录 are included.

数据附录 chart input summaries must include:

- 股票身份、代码、名称。
- `source` and fallback source when available.
- `candle_count`, `has_volume`, `has_ma5`, `has_ma20`, and `has_ma40`.
- Price ladder summary with 中文名, value, source/source label, kind, and dynamic/static flag.

Markdown is an optional clean-text export. It should avoid raw HTML layout by default. PDF is exported from the rendered HTML on demand.

动作桶固定为：`必须执行`、`条件执行`、`观察等待`、`禁止动作`。

## 关注池赔率规则

关注池技术跟踪不是建仓清单。网页主报告不默认计算或展示关注池赔率。

Only calculate/display odds when an actual build/add action has a complete buy point, target, and stop. Watchlist tracking must not display `0:1`, and must not use missing target/stop copy as the visible web action.

关注池在网页中只展示：

- 技术跟踪。
- 当前技术状态。
- 上方压力、当前价、下方支撑、硬止损等价位信息。
- 是否需要等待回踩确认或有效突破。

## 补数报告结构

数据闸门 BLOCK 时，`run` 默认会写 HTML 补数报告：

```text
reports/YYYY-MM-DD-HHMM-data-block.html
```

HTML data-block report should include:

- Report time and data gate status.
- BLOCK items with source names, reasons, and missing fields.
- Refill tasks, including source URL, override path, override key, expected status, success criteria, required fields, and example override when available.
- Raw evidence references, including gate JSON or related source artifacts.

补数报告的职责是告诉用户缺什么、去哪里补、覆盖文件怎么写。它不是交易报告，也不能生成正式买卖建议。

## 语言和边界

报告文字要给动作、条件、触发位、仓位和风险边界。可以写“条件买入”“先减仓”“退出”“继续观察”；不要写确定性承诺，例如“必涨”“保证收益”“今天必须买入”。
