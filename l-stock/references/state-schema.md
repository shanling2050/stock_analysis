# State Schema

用户状态只保存在工作区的 `state/*.yaml`，不要写入 Skill 目录。初始化会创建 JSON 兼容 YAML；现有文件会保留。

## 必需文件

- `state/positions.yaml`
- `state/watchlist.yaml`
- `state/preferences.yaml`
- `state/history.yaml`

验证命令：

```bash
python3 /Users/bytedance/.codex/skills/l-stock/scripts/lstock.py validate-state --workspace "$PWD"
```

缺文件、格式错误、重复代码、非法代码或持仓与“已放弃”关注项冲突，都会 BLOCK。

## positions.yaml

顶层必须是 `positions` 列表。每个持仓必须是对象，`code` 必须是六位字符串。`quantity` 和 `cost` 属于高风险字段。当前 CLI 提供 `diff-positions`，持仓截图同步或手工改动前必须先展示 diff 并取得用户确认。

示例：

```json
{
  "positions": [
    {
      "code": "600000",
      "name": "浦发银行",
      "quantity": 1000,
      "cost": 7.25,
      "note": "中线观察"
    }
  ]
}
```

## watchlist.yaml

顶层必须是 `watchlist` 列表。每个关注项必须是对象，`code` 必须是六位字符串。用于条件买入判断时，建议维护 `price`、`target`、`stop`、`signal`。

示例：

```json
{
  "watchlist": [
    {
      "code": "000001",
      "name": "平安银行",
      "price": 10.0,
      "target": 12.5,
      "stop": 9.2,
      "signal": "放量突破后回踩确认",
      "status": "观察"
    }
  ]
}
```

如果关注项 `status` 为 `已放弃`，同一代码不能仍在 `positions` 中持有。

## preferences.yaml

必须包含 `risk`、`report`、`data` 三个映射。默认值如下：

```json
{
  "risk": {
    "reserve_cash_ratio": 0.2,
    "max_loss_per_trade_ratio": 0.02,
    "minimum_odds_ratio": 2.0
  },
  "report": {
    "language": "zh-CN",
    "first_page_action_only": true
  },
  "data": {
    "allow_stale_margin_data": true,
    "default_market": "A-share"
  }
}
```

`reserve_cash_ratio` 默认 0.2，即至少保留 20% 现金。`minimum_odds_ratio` 默认 2.0，即关注池买入赔率下限为 2:1。

## history.yaml

顶层必须是 `events` 列表，用于记录用户确认过的状态变更、复盘备注或重要交易事件。

示例：

```json
{
  "events": [
    {
      "date": "2026-06-23",
      "type": "state_confirmed",
      "note": "用户确认持仓截图同步结果"
    }
  ]
}
```

## 截图同步纪律

当用户提供持仓截图时，先提取为结构化 JSON，再调用 `lstock_state.py diff-positions` 比对当前 `positions.yaml`。`diff-positions` 会先验证当前状态；若返回 `status: BLOCK` / `reason: invalid_state`，必须先修复状态文件，不能继续应用截图差异。对新增持仓、数量变化、成本变化、截图缺失持仓等结果，必须展示 diff 并取得用户确认后再写 `state/*.yaml`。

当用户提供关注池截图或用自然语言要求修改关注池时，当前还没有 watchlist diff 命令。Codex 应手工列出将要新增、删除或修改的关注项摘要，向用户确认后再编辑 `state/watchlist.yaml`。
