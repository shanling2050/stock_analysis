#!/usr/bin/env python3
"""CLI orchestrator for l-stock workspace commands."""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


SCRIPTS_DIR = Path(__file__).resolve().parent
INIT_SCRIPT = SCRIPTS_DIR / "lstock_init.py"
STATE_SCRIPT = SCRIPTS_DIR / "lstock_state.py"
DATA_SCRIPT = SCRIPTS_DIR / "lstock_data.py"
REPORT_SCRIPT = SCRIPTS_DIR / "lstock_report.py"


class JsonCliError(Exception):
    """Raised for CLI input errors that should be rendered as JSON."""


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise JsonCliError(message)

    def exit(self, status: int = 0, message: Optional[str] = None) -> None:
        if status:
            raise JsonCliError((message or f"exit status {status}").strip())
        raise SystemExit(status)


def print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cli_error(message: str, **extra: Any) -> int:
    payload: dict[str, Any] = {"status": "ERROR", "error": message}
    payload.update({key: value for key, value in extra.items() if value not in (None, "")})
    print_json(payload)
    return 1


def local_minute_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H%M")


def run_streamed(command: list[str]) -> int:
    return subprocess.run(command).returncode


def run_captured(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True)


def load_child_json(result: subprocess.CompletedProcess[str], label: str) -> tuple[Optional[dict[str, Any]], int]:
    if result.returncode != 0:
        return None, cli_error(
            f"{label} failed",
            returncode=result.returncode,
            stdout=result.stdout.strip(),
            stderr=result.stderr.strip(),
        )

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        return None, cli_error(
            f"{label} did not return valid JSON",
            detail=f"{error.msg} at line {error.lineno}, column {error.colno}",
            stdout=result.stdout.strip(),
            stderr=result.stderr.strip(),
        )
    if not isinstance(payload, dict):
        return None, cli_error(f"{label} returned JSON that is not an object")
    return payload, 0


def workspace_path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def ensure_run_logs(workspace: Path) -> Path:
    run_logs = workspace / "cache" / "run_logs"
    run_logs.mkdir(parents=True, exist_ok=True)
    return run_logs


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def collect_snapshot(workspace: Path, offline: bool) -> tuple[Optional[dict[str, Any]], int]:
    command = [sys.executable, str(DATA_SCRIPT), "collect", "--workspace", str(workspace)]
    if offline:
        command.append("--offline")
    result = run_captured(command)
    return load_child_json(result, "collect")


def gate_status(snapshot: dict[str, Any]) -> str:
    gate = snapshot.get("gate")
    if isinstance(gate, dict):
        return str(gate.get("status", "UNKNOWN"))
    return "UNKNOWN"


def report_name(workspace: Path, stamp: str, gate: str, extension: str = "html") -> Path:
    reports_dir = workspace / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    suffix = extension.lstrip(".")
    stem = stamp if gate in {"PASS", "WARN"} else f"{stamp}-data-block"
    candidate = reports_dir / f"{stem}.{suffix}"
    if not candidate.exists():
        return candidate

    counter = 2
    while True:
        candidate = reports_dir / f"{stem}-{counter:02d}.{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def export_name(workspace: Path, source_path: Path, extension: str) -> Path:
    output_dir = workspace / "reports" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = extension.lstrip(".")
    stem = export_stem(source_path)
    candidate = output_dir / f"{stem}.{suffix}"
    if not candidate.exists():
        return candidate

    counter = 2
    while True:
        candidate = output_dir / f"{stem}-{counter:02d}.{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def export_stem(source_path: Path) -> str:
    stem = source_path.stem
    numbered_snapshot = re.match(r"^(?P<base>.+)-snapshot-(?P<counter>\d+)$", stem)
    if numbered_snapshot:
        return f"{numbered_snapshot.group('base')}-{numbered_snapshot.group('counter')}"
    if stem.endswith("-snapshot"):
        return stem[: -len("-snapshot")]
    return stem


def snapshot_name(workspace: Path, stamp: str) -> Path:
    run_logs = ensure_run_logs(workspace)
    candidate = run_logs / f"{stamp}-snapshot.json"
    if not candidate.exists():
        return candidate

    counter = 2
    while True:
        candidate = run_logs / f"{stamp}-snapshot-{counter:02d}.json"
        if not candidate.exists():
            return candidate
        counter += 1


def init_command(workspace: Path) -> list[str]:
    return [sys.executable, str(INIT_SCRIPT), "--workspace", str(workspace)]


def resolve_workspace_file(workspace: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = workspace / path
    return path.resolve()


def render_report(snapshot_path: Path, report_path: Path) -> int:
    result = run_captured(
        [
            sys.executable,
            str(REPORT_SCRIPT),
            "render-html",
            "--snapshot",
            str(snapshot_path),
            "--output",
            str(report_path),
        ]
    )
    if result.returncode != 0:
        return cli_error(
            "render failed",
            returncode=result.returncode,
            stdout=result.stdout.strip(),
            stderr=result.stderr.strip(),
        )
    return 0


def command_init(args: argparse.Namespace) -> int:
    return run_streamed(init_command(workspace_path(args.workspace)))


def command_validate_state(args: argparse.Namespace) -> int:
    workspace = workspace_path(args.workspace)
    return run_streamed([sys.executable, str(STATE_SCRIPT), "validate", "--workspace", str(workspace)])


def command_data_gate(args: argparse.Namespace) -> int:
    workspace = workspace_path(args.workspace)
    snapshot, exit_code = collect_snapshot(workspace, args.offline)
    if snapshot is None:
        return exit_code

    latest_snapshot = ensure_run_logs(workspace) / "latest-snapshot.json"
    try:
        write_json_file(latest_snapshot, snapshot)
    except OSError as error:
        return cli_error(f"failed to write snapshot: {error}")

    return run_streamed([sys.executable, str(DATA_SCRIPT), "gate", "--snapshot", str(latest_snapshot)])


def command_export_md(args: argparse.Namespace) -> int:
    workspace = workspace_path(args.workspace)
    snapshot_path = resolve_workspace_file(workspace, args.snapshot)
    output_path = resolve_workspace_file(workspace, args.output) if args.output else export_name(workspace, snapshot_path, "md")
    command = [
        sys.executable,
        str(REPORT_SCRIPT),
        "render-md",
        "--snapshot",
        str(snapshot_path),
        "--output",
        str(output_path),
    ]
    if args.with_images:
        command.append("--with-images")

    payload, exit_code = load_child_json(run_captured(command), "export-md")
    if payload is None:
        return exit_code
    print_json(payload)
    return 0


def command_export_pdf(args: argparse.Namespace) -> int:
    workspace = workspace_path(args.workspace)
    report_path = resolve_workspace_file(workspace, args.report)
    output_path = resolve_workspace_file(workspace, args.output) if args.output else export_name(workspace, report_path, "pdf")
    command = [
        sys.executable,
        str(REPORT_SCRIPT),
        "export-pdf",
        "--report",
        str(report_path),
        "--output",
        str(output_path),
    ]

    payload, exit_code = load_child_json(run_captured(command), "export-pdf")
    if payload is None:
        return exit_code
    print_json(payload)
    return 0


def command_run(args: argparse.Namespace) -> int:
    workspace = workspace_path(args.workspace)

    init_result = run_captured(init_command(workspace))
    if init_result.returncode != 0:
        return cli_error(
            "init failed",
            returncode=init_result.returncode,
            stdout=init_result.stdout.strip(),
            stderr=init_result.stderr.strip(),
        )

    snapshot, exit_code = collect_snapshot(workspace, args.offline)
    if snapshot is None:
        return exit_code

    stamp = local_minute_stamp()
    run_logs = ensure_run_logs(workspace)
    snapshot_path = snapshot_name(workspace, stamp)
    latest_snapshot = run_logs / "latest-snapshot.json"
    try:
        write_json_file(snapshot_path, snapshot)
        write_json_file(latest_snapshot, snapshot)
    except OSError as error:
        return cli_error(f"failed to write snapshot: {error}")

    gate = gate_status(snapshot)
    report_path = report_name(workspace, stamp, gate)
    render_exit = render_report(snapshot_path, report_path)
    if render_exit != 0:
        return render_exit

    status = "OK" if gate in {"PASS", "WARN"} else "BLOCK"
    print_json(
        {
            "status": status,
            "gate_status": gate,
            "snapshot": str(snapshot_path),
            "report": str(report_path),
        }
    )
    return 0 if gate in {"PASS", "WARN"} else 2


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = JsonArgumentParser(description="l-stock CLI orchestrator")
    subcommands = parser.add_subparsers(dest="command", required=True, parser_class=JsonArgumentParser)

    init_parser = subcommands.add_parser("init", help="initialize a workspace")
    init_parser.add_argument("--workspace", default=".", help="l-stock workspace")

    validate_parser = subcommands.add_parser("validate-state", help="validate workspace state")
    validate_parser.add_argument("--workspace", default=".", help="l-stock workspace")

    gate_parser = subcommands.add_parser("data-gate", help="collect data and run the data gate")
    gate_parser.add_argument("--workspace", default=".", help="l-stock workspace")
    gate_parser.add_argument("--offline", action="store_true", help="skip network fetches")

    run_parser = subcommands.add_parser("run", help="collect data and render a report")
    run_parser.add_argument("--workspace", default=".", help="l-stock workspace")
    run_parser.add_argument("--offline", action="store_true", help="skip network fetches")

    export_md_parser = subcommands.add_parser("export-md", help="export a snapshot as Markdown")
    export_md_parser.add_argument("--workspace", default=".", help="l-stock workspace")
    export_md_parser.add_argument("--snapshot", required=True, help="snapshot JSON path")
    export_md_parser.add_argument("--output", help="Markdown output path")
    export_md_parser.add_argument("--with-images", action="store_true", help="write chart image assets")

    export_pdf_parser = subcommands.add_parser("export-pdf", help="export an HTML report as PDF")
    export_pdf_parser.add_argument("--workspace", default=".", help="l-stock workspace")
    export_pdf_parser.add_argument("--report", required=True, help="HTML report path")
    export_pdf_parser.add_argument("--output", help="PDF output path")

    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
        if args.command == "init":
            return command_init(args)
        if args.command == "validate-state":
            return command_validate_state(args)
        if args.command == "data-gate":
            return command_data_gate(args)
        if args.command == "run":
            return command_run(args)
        if args.command == "export-md":
            return command_export_md(args)
        if args.command == "export-pdf":
            return command_export_pdf(args)
        raise JsonCliError(f"unknown command: {args.command}")
    except JsonCliError as error:
        return cli_error(str(error))
    except Exception as error:
        return cli_error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
