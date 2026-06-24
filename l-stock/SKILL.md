---
name: l-stock
description: A股每日交易诊断与持仓/关注池管理。Use when the user invokes [$l-stock], asks to initialize or run l-stock, sends A-share position/watchlist screenshots, asks for daily A-share market/sector/portfolio diagnostic reports, or asks to update/delete tracked A-share holdings/watchlist state.
---

# l-stock

Use this Skill to maintain an A-share trading workspace and generate actionable daily reports.

## Core Rules

- Treat the current working directory as the user's l-stock workspace.
- Keep user state in the workspace, not inside the Skill folder.
- Do not persist screenshots by default.
- Do not generate a formal report when critical data is missing.
- Confirm before writing changes to holdings, costs, quantities, or watchlist membership.
- Never place orders or imply guaranteed outcomes.

## Command Routing

For `初始化`, run:

```bash
python3 /Users/bytedance/.codex/skills/l-stock/scripts/lstock.py init --workspace "$PWD"
```

For `跑一次`, run:

```bash
python3 /Users/bytedance/.codex/skills/l-stock/scripts/lstock.py run --workspace "$PWD"
```

For state validation, run:

```bash
python3 /Users/bytedance/.codex/skills/l-stock/scripts/lstock.py validate-state --workspace "$PWD"
```

For data gate only, run:

```bash
python3 /Users/bytedance/.codex/skills/l-stock/scripts/lstock.py data-gate --workspace "$PWD"
```

## Reference Routing

- Read `references/workflow.md` for the run lifecycle.
- Read `references/state-schema.md` before editing `state/*.yaml`.
- Read `references/data-sources.md` before gathering or补数 data.
- Read `references/decision-rules.md` before generating recommendations.
- Read `references/report-template.md` before writing Markdown reports.
- Read `references/failure-handling.md` when data, state, liquidity, or model-boundary issues appear.

## Screenshot Handling

When the user provides a position or watchlist screenshot, use Codex vision to extract a table, compare it with state through `lstock_state.py`, show the diff, and ask for confirmation before writing changes.
