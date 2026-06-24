#!/usr/bin/env python3
"""State helpers for l-stock workspaces."""

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


REQUIRED_STATE_FILES = [
    "positions.yaml",
    "watchlist.yaml",
    "preferences.yaml",
    "history.yaml",
]
CODE_RE = re.compile(r"^\d{6}$")


def load_json_yaml(path: Path) -> dict[str, Any]:
    """Load JSON-compatible YAML, using PyYAML for broader YAML if available."""
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}

    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as json_error:
        try:
            import yaml  # type: ignore
        except Exception as yaml_import_error:
            raise ValueError(
                f"{path} is not JSON-compatible YAML: {json_error.msg} "
                f"at line {json_error.lineno}, column {json_error.colno}; "
                "PyYAML is not installed for non-JSON YAML fallback"
            ) from yaml_import_error

        try:
            loaded = yaml.safe_load(text)
        except Exception as yaml_error:
            raise ValueError(
                f"{path} could not be parsed as JSON or YAML: JSON error "
                f"{json_error.msg} at line {json_error.lineno}, column {json_error.colno}; "
                f"YAML error {yaml_error}"
            ) from yaml_error

    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a mapping/object at the top level")
    return loaded


def save_json_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def state_dir(workspace: Path) -> Path:
    return workspace / "state"


def load_state(workspace: Path) -> dict[str, dict[str, Any]]:
    root = state_dir(workspace)
    return {
        "positions": load_json_yaml(root / "positions.yaml"),
        "watchlist": load_json_yaml(root / "watchlist.yaml"),
        "preferences": load_json_yaml(root / "preferences.yaml"),
        "history": load_json_yaml(root / "history.yaml"),
    }


def validate_code(code: Any) -> bool:
    return isinstance(code, str) and bool(CODE_RE.fullmatch(code))


def _as_list(value: Any, file_label: str, key: str, errors: list[dict[str, Any]]) -> list[Any]:
    if isinstance(value, list):
        return value
    errors.append({"type": "invalid_state_shape", "file": file_label, "key": key, "expected": "list"})
    return []


def _required_list(data: dict[str, Any], file_label: str, key: str, errors: list[dict[str, Any]]) -> list[Any]:
    if key not in data:
        errors.append({"type": "missing_required_key", "file": file_label, "key": key})
        return []
    return _as_list(data[key], file_label, key, errors)


def _validate_preferences(preferences: dict[str, Any], errors: list[dict[str, Any]]) -> None:
    file_label = "preferences.yaml"
    if not preferences:
        errors.append({"type": "invalid_state_shape", "file": file_label, "expected": "non-empty mapping"})
        return

    for key in ("risk", "report", "data"):
        if key not in preferences:
            errors.append({"type": "missing_required_key", "file": file_label, "key": key})
            continue
        if not isinstance(preferences[key], dict):
            errors.append({"type": "invalid_state_shape", "file": file_label, "key": key, "expected": "mapping"})


def _missing_required_files(workspace: Path) -> list[str]:
    root = state_dir(workspace)
    return [name for name in REQUIRED_STATE_FILES if not (root / name).is_file()]


def validate_state(workspace: Path) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    missing = _missing_required_files(workspace)
    if missing:
        errors.append({"type": "missing_state_files", "files": missing})
        return {"status": "BLOCK", "errors": errors}

    try:
        data = load_state(workspace)
    except (OSError, ValueError) as error:
        errors.append({"type": "unreadable_state", "message": str(error)})
        return {"status": "BLOCK", "errors": errors}

    positions = _required_list(data["positions"], "positions.yaml", "positions", errors)
    watchlist = _required_list(data["watchlist"], "watchlist.yaml", "watchlist", errors)
    _required_list(data["history"], "history.yaml", "events", errors)
    _validate_preferences(data["preferences"], errors)

    position_codes: set[str] = set()
    first_position_index: dict[str, int] = {}
    for index, item in enumerate(positions):
        if not isinstance(item, dict):
            errors.append({"type": "invalid_position_item", "index": index, "item": item})
            continue
        code = item.get("code")
        if not validate_code(code):
            errors.append({"type": "invalid_position_code", "index": index, "code": code})
            continue
        if code in first_position_index:
            errors.append(
                {
                    "type": "duplicate_position_code",
                    "code": code,
                    "index": index,
                    "first_index": first_position_index[code],
                }
            )
            continue
        position_codes.add(code)
        first_position_index[code] = index

    abandoned_codes: set[str] = set()
    first_watchlist_index: dict[str, int] = {}
    for index, item in enumerate(watchlist):
        if not isinstance(item, dict):
            errors.append({"type": "invalid_watchlist_item", "index": index, "item": item})
            continue
        code = item.get("code")
        if not validate_code(code):
            errors.append({"type": "invalid_watchlist_code", "index": index, "code": code})
            continue
        if code in first_watchlist_index:
            errors.append(
                {
                    "type": "duplicate_watchlist_code",
                    "code": code,
                    "index": index,
                    "first_index": first_watchlist_index[code],
                }
            )
            continue
        first_watchlist_index[code] = index
        if item.get("status") == "已放弃":
            abandoned_codes.add(code)

    conflicts = sorted(position_codes & abandoned_codes)
    if conflicts:
        errors.append({"type": "held_but_abandoned", "codes": conflicts})

    return {"status": "PASS" if not errors else "BLOCK", "errors": errors}


def backup_state(workspace: Path) -> Path:
    missing = _missing_required_files(workspace)
    if missing:
        raise FileNotFoundError(f"Missing required state files: {', '.join(missing)}")

    root = state_dir(workspace)
    backup_root = root / ".backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    destination = backup_root / stamp
    counter = 1
    while destination.exists():
        destination = backup_root / f"{stamp}-{counter:02d}"
        counter += 1
    destination.mkdir(parents=True, exist_ok=False)

    for name in REQUIRED_STATE_FILES:
        shutil.copy2(root / name, destination / name)
    return destination


def _load_incoming_positions(incoming_path: Path) -> list[dict[str, Any]]:
    try:
        incoming = json.loads(incoming_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(
            f"{incoming_path} is not valid JSON: {error.msg} "
            f"at line {error.lineno}, column {error.colno}"
        ) from error
    if not isinstance(incoming, dict):
        raise ValueError(f"{incoming_path} must contain a JSON object")
    if "positions" not in incoming:
        raise ValueError(f"{incoming_path} missing required field 'positions'")
    positions = incoming["positions"]
    if not isinstance(positions, list):
        raise ValueError(f"{incoming_path} field 'positions' must be a list")
    for index, item in enumerate(positions):
        if not isinstance(item, dict):
            raise ValueError(f"{incoming_path} positions[{index}] must be an object")
    return positions


def _positions_by_code(items: list[Any], label: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    first_seen: dict[str, int] = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"{label}[{index}] must be an object")
        code = item.get("code")
        if not validate_code(code):
            raise ValueError(f"{label}[{index}] has invalid stock code {code!r}; expected six digits")
        if code in indexed:
            raise ValueError(
                f"{label}[{index}] duplicate stock code {code!r}; "
                f"first seen at {label}[{first_seen[code]}]"
            )
        indexed[code] = item
        first_seen[code] = index
    return indexed


def diff_positions(workspace: Path, incoming_path: Path) -> dict[str, Any]:
    validation = validate_state(workspace)
    if validation.get("status") == "BLOCK":
        return {
            "status": "BLOCK",
            "reason": "invalid_state",
            "errors": validation.get("errors", []),
            "requires_confirmation": False,
            "changes": [],
        }

    state = load_state(workspace)
    current_positions = state["positions"]["positions"]

    incoming_positions = _load_incoming_positions(incoming_path)
    current_by_code = _positions_by_code(current_positions, "current positions")
    incoming_by_code = _positions_by_code(incoming_positions, "incoming positions")

    changes: list[dict[str, Any]] = []
    for code in sorted(incoming_by_code):
        incoming = incoming_by_code[code]
        current = current_by_code.get(code)
        if current is None:
            changes.append({"type": "new_position", "code": code, "incoming": incoming})
            continue

        for field in ("quantity", "cost"):
            if current.get(field) != incoming.get(field):
                changes.append(
                    {
                        "type": f"{field}_changed",
                        "code": code,
                        "old": current.get(field),
                        "new": incoming.get(field),
                        "current": current,
                        "incoming": incoming,
                    }
                )

    for code in sorted(current_by_code):
        if code not in incoming_by_code:
            changes.append({"type": "missing_from_incoming", "code": code, "current": current_by_code[code]})

    risky_types = {"new_position", "quantity_changed", "cost_changed", "missing_from_incoming"}
    return {
        "requires_confirmation": any(change["type"] in risky_types for change in changes),
        "changes": changes,
    }


def _add_workspace_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace", default=".", help="l-stock workspace directory")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load, validate, back up, and diff l-stock state")
    subcommands = parser.add_subparsers(dest="command", required=True)

    validate_parser = subcommands.add_parser("validate", help="validate required state files")
    _add_workspace_arg(validate_parser)

    diff_parser = subcommands.add_parser("diff-positions", help="compare current positions with incoming JSON")
    _add_workspace_arg(diff_parser)
    diff_parser.add_argument("--incoming", required=True, help="path to incoming JSON file")

    backup_parser = subcommands.add_parser("backup", help="back up required state files")
    _add_workspace_arg(backup_parser)

    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    workspace = Path(args.workspace).expanduser().resolve()

    try:
        if args.command == "validate":
            payload = validate_state(workspace)
        elif args.command == "diff-positions":
            payload = diff_positions(workspace, Path(args.incoming).expanduser().resolve())
        elif args.command == "backup":
            payload = {"backup": str(backup_state(workspace))}
        else:
            raise ValueError(f"Unknown command: {args.command}")
    except Exception as error:
        print(json.dumps({"status": "ERROR", "error": str(error)}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
