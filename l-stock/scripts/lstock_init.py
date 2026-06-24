#!/usr/bin/env python3
"""Initialize an l-stock workspace with required directories and state files."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Initialize l-stock workspace")
    parser.add_argument(
        "--workspace",
        default=".",
        help="Workspace directory to initialize",
    )
    return parser.parse_args()


def ensure_directory(path: Path) -> bool:
    if path.exists():
        if not path.is_dir():
            raise NotADirectoryError(f"{path} exists and is not a directory")
        return False
    path.mkdir(parents=True, exist_ok=True)
    return True


def ensure_yaml_file(path: Path, payload: dict) -> bool:
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    if path.exists():
        return False
    path.write_text(content, encoding="utf-8")
    return True


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).expanduser().resolve()
    created = []
    preserved = []

    state_dir = workspace / "state"
    reports_dir = workspace / "reports"
    cache_dir = workspace / "cache"
    backups_dir = state_dir / ".backups"
    last_good_dir = cache_dir / "last_good"
    run_logs_dir = cache_dir / "run_logs"

    if ensure_directory(state_dir):
        created.append("state")
    else:
        preserved.append("state")

    if ensure_directory(reports_dir):
        created.append("reports")
    else:
        preserved.append("reports")

    if ensure_directory(cache_dir):
        created.append("cache")
    else:
        preserved.append("cache")

    if ensure_directory(backups_dir):
        created.append("state/.backups")
    else:
        preserved.append("state/.backups")

    if ensure_directory(last_good_dir):
        created.append("cache/last_good")
    else:
        preserved.append("cache/last_good")

    if ensure_directory(run_logs_dir):
        created.append("cache/run_logs")
    else:
        preserved.append("cache/run_logs")

    defaults = {
        "positions": [],
        "watchlist": [],
        "preferences": {
            "risk": {
                "reserve_cash_ratio": 0.2,
                "max_loss_per_trade_ratio": 0.02,
                "minimum_odds_ratio": 2.0,
            },
            "report": {
                "language": "zh-CN",
                "first_page_action_only": True,
            },
            "data": {
                "allow_stale_margin_data": True,
                "default_market": "A-share",
            },
        },
        "history": [],
    }

    if ensure_yaml_file(state_dir / "positions.yaml", {"positions": defaults["positions"]}):
        created.append("state/positions.yaml")
    else:
        preserved.append("state/positions.yaml")

    if ensure_yaml_file(state_dir / "watchlist.yaml", {"watchlist": defaults["watchlist"]}):
        created.append("state/watchlist.yaml")
    else:
        preserved.append("state/watchlist.yaml")

    if ensure_yaml_file(state_dir / "preferences.yaml", defaults["preferences"]):
        created.append("state/preferences.yaml")
    else:
        preserved.append("state/preferences.yaml")

    if ensure_yaml_file(state_dir / "history.yaml", {"events": defaults["history"]}):
        created.append("state/history.yaml")
    else:
        preserved.append("state/history.yaml")

    payload = {
        "workspace": str(workspace),
        "created": created,
        "preserved": preserved,
        "initialized_at": datetime.now(timezone.utc).isoformat(),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
