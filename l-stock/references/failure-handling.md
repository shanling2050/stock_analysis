# Failure Handling

失败处理的原则：先保护状态和数据完整性，再生成结论。关键数据 BLOCK 时，不给正式买卖建议。

## 命令失败

主命令：

```bash
python3 /Users/bytedance/.codex/skills/l-stock/scripts/lstock.py run --workspace "$PWD"
```

可能退出：

- `0`：运行完成，`gate_status` 为 PASS 或 WARN。
- `2`：数据闸门 BLOCK；已写快照和 `*-data-block.md` 补数报告。
- `1`：初始化、采集、渲染或参数错误；stdout 会包含 `status: ERROR` 和错误信息。

遇到退出 `2` 不要当作脚本崩溃。先打开 JSON stdout 中的 `report`，按补数任务处理。

## 状态问题

`state` BLOCK 时，先运行：

```bash
python3 /Users/bytedance/.codex/skills/l-stock/scripts/lstock.py validate-state --workspace "$PWD"
```

常见原因：

- 缺少 `positions.yaml`、`watchlist.yaml`、`preferences.yaml` 或 `history.yaml`。
- 顶层字段不是列表或映射。
- 股票代码不是六位字符串。
- 持仓或关注池中代码重复。
- 某代码仍持仓，但关注池状态为 `已放弃`。

修复状态文件前，若涉及持仓、成本、数量或关注池成员变动，必须先向用户确认。

## 数据源问题

`market` 或 `stocks` BLOCK 通常来自网络失败、东方财富接口异常、K 线不足 40 根或离线模式。处理顺序：

1. 确认是否使用了 `--offline`。
2. 重跑一次，排除临时网络问题。
3. 若报告列出 `market` 或 `stocks` 的 Chrome 补数任务，按任务要求从最新行情/K 线页面补齐 `source-overrides.json`。
4. 若个股长期缺 K 线，检查代码是否正确或是否为不支持的品种。
5. 仍无法确认时保留 BLOCK，不补写假数据。

`funds`、`sectors`、`emotion` 会先尝试 Python 自动采集；BLOCK 时，按报告中的 Chrome 补数任务写 `cache/run_logs/source-overrides.json`。在线运行时，只有本轮 Python/默认采集 BLOCK 的分组才会读取覆盖；Python 已经 PASS 的分组不会被旧覆盖替换。如果没有分组需要覆盖，坏的旧覆盖文件不会影响本轮运行；如果需要覆盖但整个文件不可读取、不是合法 JSON 或根节点不是对象，对应分组会 BLOCK 为 `invalid_source_override_file`；如果某个分组值不是对象、字段不完整或字段值无效，对应分组会 BLOCK 为 `invalid_source_override`。PASS 覆盖必须满足 `required_fields` 且字段值有效，部分覆盖、空值覆盖或漏掉应补代码都无效。

无效覆盖示例：

```json
{
  "emotion": {
    "status": "PASS"
  }
}
```

有效覆盖示例：

```json
{
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

## 报告问题

如果 `run` 已写快照但渲染失败，检查 stdout 中的 `render failed`、`stdout` 和 `stderr`。不要直接手写正式报告替代渲染；先修快照或报告输入。

## 交易边界

任何失败场景下都不能：

- 直接下单或替用户点击交易。
- 承诺收益、胜率或确定性涨跌。
- 在 MA40 破位后建议摊低成本。
- 在数据 BLOCK 时给正式买卖动作。

可以做的是：解释缺失项、给补数步骤、列出风险、等待用户确认状态变更。
