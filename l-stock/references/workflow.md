# Workflow

`l-stock` 是 A 股交易诊断工作流。它只做决策支持，不下单、不保证收益、不替用户承担交易责任。

## 主命令

在用户的 l-stock 工作区执行：

```bash
python3 /Users/bytedance/.codex/skills/l-stock/scripts/lstock.py run --workspace "$PWD"
```

工作区内固定使用这些目录：

- `state/*.yaml`：用户状态，包含持仓、关注池、偏好和历史事件。
- `reports/`：每次运行生成的 Markdown 报告。
- `cache/run_logs/`：每次运行的快照、最新快照和 Chrome 补数覆盖文件。

## 运行生命周期

1. `run` 会先执行初始化逻辑。初始化是幂等的：已存在的目录和状态文件会保留，不覆盖用户数据。
2. 采集快照，写入 `cache/run_logs/YYYY-MM-DD-HHMM-snapshot.json`，同时覆盖 `cache/run_logs/latest-snapshot.json`。
3. 执行数据闸门。闸门分组固定为：`state`、`market`、`stocks`、`funds`、`sectors`、`emotion`。
4. 渲染报告到 `reports/`。
5. stdout 输出 JSON，供 Codex 判断下一步。

PASS 或 WARN 时，报告名为：

```text
reports/YYYY-MM-DD-HHMM.md
```

BLOCK 时，报告名为：

```text
reports/YYYY-MM-DD-HHMM-data-block.md
```

同一分钟内重复运行时，快照和报告都会自动追加 `-02`、`-03` 等后缀，避免覆盖。只有 `cache/run_logs/latest-snapshot.json` 每次覆盖。

## 退出码和 stdout

`run` 成功通过数据闸门时退出 `0`：

```json
{
  "status": "OK",
  "gate_status": "PASS",
  "snapshot": "/workspace/cache/run_logs/2026-06-23-1530-snapshot.json",
  "report": "/workspace/reports/2026-06-23-1530.md"
}
```

`run` 遇到 BLOCK 时仍会写快照和补数报告，但退出 `2`：

```json
{
  "status": "BLOCK",
  "gate_status": "BLOCK",
  "snapshot": "/workspace/cache/run_logs/2026-06-23-1530-snapshot.json",
  "report": "/workspace/reports/2026-06-23-1530-data-block.md"
}
```

`data-gate` 只采集和检查数据：它会覆盖 `cache/run_logs/latest-snapshot.json`，然后调用闸门检查。闸门 BLOCK 时退出 `2`，非 BLOCK 时退出 `0`。

## BLOCK 后的标准动作

1. 打开 `*-data-block.md`，先看 `BLOCK 项`。
2. 如果报告列出 `Chrome 补数任务`，按报告中渲染出来的 `url`、`required_fields`、`override_path`、`override_key`、`expected_status`、`success_criteria` 和 `example_override` 补齐来源。任务可能来自 `funds`、`sectors`、`emotion`，也可能来自 Python K 线失败后的 `market` 或 `stocks`。
3. 将覆盖写入 `cache/run_logs/source-overrides.json`。
4. 重新执行主命令；在线运行时，覆盖只补本轮仍 BLOCK 的分组，Python 已经 PASS 的分组会继续使用最新自动采集结果。

不要在 BLOCK 报告中给正式买卖建议。BLOCK 的含义是关键数据不足，必须先补数或修正状态。
