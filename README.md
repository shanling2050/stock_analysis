# l-stock

A股每日交易诊断与持仓/关注池管理工具。

## 功能

- **工作区初始化**：创建标准化的工作目录结构和状态文件
- **数据采集**：自动采集 A 股市场、股票、基金、板块和情绪数据
- **数据闸门**：验证数据完整性，确保报告质量
- **报告生成**：生成 HTML 格式的每日诊断报告
- **状态管理**：管理持仓、关注池、偏好设置和历史事件

## 项目结构

```
l-stock/
├── agents/
│   └── openai.yaml
├── references/
│   ├── data-sources.md
│   ├── decision-rules.md
│   ├── failure-handling.md
│   ├── report-template.md
│   ├── state-schema.md
│   └── workflow.md
├── scripts/
│   ├── cache/
│   │   └── run_logs/
│   ├── reports/
│   ├── state/
│   │   ├── positions.yaml
│   │   ├── watchlist.yaml
│   │   ├── preferences.yaml
│   │   └── history.yaml
│   ├── lstock.py
│   ├── lstock_data.py
│   ├── lstock_init.py
│   ├── lstock_report.py
│   └── lstock_state.py
├── tests/
│   └── lstock_regression_test.py
└── SKILL.md
```

## 快速开始

### 初始化工作区

```bash
cd /path/to/workspace
python3 l-stock/scripts/lstock.py init --workspace .
```

### 运行完整诊断

```bash
python3 l-stock/scripts/lstock.py run --workspace .
```

### 验证状态文件

```bash
python3 l-stock/scripts/lstock.py validate-state --workspace .
```

### 仅执行数据闸门

```bash
python3 l-stock/scripts/lstock.py data-gate --workspace .
```

## CLI 命令

| 命令 | 描述 |
|------|------|
| `init` | 初始化工作区 |
| `run` | 采集数据并生成报告 |
| `validate-state` | 验证工作区状态 |
| `data-gate` | 采集数据并运行数据闸门 |
| `export-md` | 导出快照为 Markdown |
| `export-pdf` | 导出 HTML 报告为 PDF |

## 状态文件说明

- **positions.yaml**：持仓列表，包含代码、名称、数量、成本等信息
- **watchlist.yaml**：关注池列表，用于条件买入判断
- **preferences.yaml**：偏好设置，包含风险参数、报告语言等
- **history.yaml**：历史事件记录

## 运行生命周期

1. 执行初始化（幂等操作）
2. 采集快照并写入 `cache/run_logs/`
3. 执行数据闸门检查
4. 渲染报告到 `reports/`
5. 输出 JSON 结果

## 数据闸门状态

- **PASS**：所有数据组检查通过
- **WARN**：部分数据组有警告但可继续
- **BLOCK**：关键数据不足，需补数后重新运行

## 注意事项

- 本工具仅做决策支持，不执行下单操作
- 不保证投资收益，不承担交易责任
- 状态文件修改前请先验证并确认
- 数据 BLOCK 时需先补数，不要依赖不完整数据做决策