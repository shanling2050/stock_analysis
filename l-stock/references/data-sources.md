# Data Sources

数据闸门分组固定为：`state`、`market`、`stocks`、`funds`、`sectors`、`emotion`。任一关键分组为 BLOCK，正式交易报告不得生成，`run` 会输出 `*-data-block.md`。

## Python 自动采集

`market` 和 `stocks` 使用东方财富日 K 数据：

- 指数：`000300`、`000905`、`399006`。
- 个股/基金：来自 `state/positions.yaml` 和 `state/watchlist.yaml` 的六位代码。
- 指标：MA5、MA10、MA20、MA40、MA60；少于 40 根 K 线时该证券 BLOCK。

`state` 分组读取并验证：

- `state/positions.yaml`
- `state/watchlist.yaml`
- `state/preferences.yaml`
- `state/history.yaml`

## Python 自动采集 + Chrome 补数

`funds`、`sectors`、`emotion` 也会先尝试 Python 自动采集；网络失败、解析失败或字段不可信时，才生成 Chrome 补数任务：

- `funds`：集思录 ETF 规模变化，`https://www.jisilu.cn/data/etf/`
- `sectors`：东方财富行业资金流向，`https://data.eastmoney.com/bkzj/hy.html`
- `emotion`：东方财富涨停板，`https://quote.eastmoney.com/ztb/`

`market` 和 `stocks` 优先由 Python 抓东方财富 K 线；如果网络、接口、离线模式或 K 线不足导致 BLOCK，也会生成 Chrome 补数任务：

- `market`：指数 K 线与均线，`https://quote.eastmoney.com/center/hszs.html`
- `stocks`：持仓/关注股 K 线与均线，`https://quote.eastmoney.com/`

原始快照中的 Chrome task payload 包含完整补数契约。关键字段包括：

- `override_path`
- `override_key`
- `expected_status`
- `required_fields`
- `example_override`
- `success_criteria`

当前 `*-data-block.md` 渲染报告会打印 `url`、`override_path`、`override_key`、`expected_status`、`success_criteria`、`required_fields` 和 `example_override`。如需查看完整原始任务，读取同次运行的 snapshot JSON 或 `latest-snapshot.json` 中的 `chrome_tasks`。

必须按任务要求补齐数据。只写 `{ "status": "PASS" }` 是无效覆盖，会继续 BLOCK。

## source-overrides.json

覆盖文件固定位置：

```text
cache/run_logs/source-overrides.json
```

示例：

```json
{
  "market": {
    "status": "PASS",
    "source": "chrome",
    "items": [
      {
        "code": "000300",
        "name": "沪深300",
        "close": 3810.5,
        "ma20": 3760.2,
        "ma40": 3688.4
      },
      {
        "code": "000905",
        "name": "中证500",
        "close": 5680.3,
        "ma20": 5620.1,
        "ma40": 5510.7
      },
      {
        "code": "399006",
        "name": "创业板指",
        "close": 2050.2,
        "ma20": 2018.5,
        "ma40": 1988.6
      }
    ]
  },
  "stocks": {
    "status": "PASS",
    "source": "chrome",
    "items": [
      {
        "code": "600183",
        "name": "生益科技",
        "close": 28.4,
        "ma20": 27.8,
        "ma40": 26.9
      }
    ]
  },
  "funds": {
    "status": "PASS",
    "source": "chrome",
    "items": [
      {
        "code": "510300",
        "name": "沪深300ETF",
        "scale_change_billion": -7.0,
        "scale_billion": 1200.0,
        "turnover": "12.3亿"
      }
    ]
  },
  "sectors": {
    "status": "PASS",
    "source": "chrome",
    "items": [
      {
        "name": "电子",
        "change_pct": 1.23,
        "main_net_inflow": "12.3亿",
        "super_large_net_inflow": "4.5亿"
      }
    ]
  },
  "emotion": {
    "status": "PASS",
    "source": "chrome",
    "limit_up_count": 62,
    "break_board_rate": 0.31,
    "height": 5,
    "leader_performance": "高标晋级良好"
  }
}
```

PASS 覆盖必须满足该分组的全部 `required_fields`，且字段值有效：`status`、`source`、`name` 等文本字段不能为空；`code` 必须是六位数字字符串；价格、均线、涨跌幅、规模、涨停家数等数值字段必须是有限数字。数组字段如 `items[].code` 要求 `items` 非空，且每一项都包含并通过对应字段校验。

覆盖还必须覆盖应补全集：`market` 必须包含 `000300`、`000905`、`399006`；`stocks` 必须包含当前 `positions` 和 `watchlist` 里的全部代码。漏掉任何代码都会 BLOCK，避免在个股 K 线缺失时生成正式买卖建议。

在线运行时，`source-overrides.json` 只在本轮 Python/默认采集 BLOCK 时生效；如果本轮 Python 数据已经 PASS，必须优先使用最新 Python 结果，避免旧 Chrome 覆盖污染当天判断。若没有任何分组需要覆盖，旧覆盖文件即使格式损坏也会被忽略；若存在需要覆盖的分组且整个覆盖文件不可读取、不是合法 JSON 或根节点不是对象，则对应分组 BLOCK 为 `invalid_source_override_file`；若某个分组值不是对象、字段不完整或字段值无效，则该分组 BLOCK 为 `invalid_source_override`。`--offline` 模式仍允许直接使用覆盖文件。

正式报告需要明确的市场环境和情绪阶段。`l-stock` 会根据指数 K 线、ETF 规模变化、涨停家数、炸板率和连板高度做保守派生；派生不出来时，关注池只能等待环境确认，不能给条件买入。

## 数据新鲜度和边界

使用网页补数时，只能录入页面最新表格或最新统计口径。无法确认来源、日期、字段含义或页面加载异常时，不要伪造 PASS；保留 BLOCK，并在回复中说明需要继续补数。
