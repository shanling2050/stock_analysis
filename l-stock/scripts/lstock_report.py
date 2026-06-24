#!/usr/bin/env python3
"""Decision rules and Markdown report rendering for l-stock."""

import argparse
import base64
import html
import json
import math
import os
import sys
import textwrap
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Optional


ACTION_BUCKETS = ["必须执行", "条件执行", "观察等待", "禁止动作"]
ACTION_DISPLAY_NAMES = {
    "必须执行": "必备交易操作",
    "条件执行": "可选交易操作",
    "观察等待": "持仓与观察",
    "禁止动作": "禁止交易",
}
HTML_REPORT_CSS = """
:root {
  color-scheme: light;
  --bg: #f4f6f8;
  --panel: #ffffff;
  --panel-soft: #f8fafc;
  --text: #111827;
  --muted: #64748b;
  --line: #d7dee8;
  --line-strong: #b8c2d0;
  --accent: #0f766e;
  --accent-strong: #115e59;
  --green: #15803d;
  --red: #b91c1c;
  --amber: #b45309;
  --blue: #1d4ed8;
  --dark: #111827;
  --shadow: 0 14px 34px rgba(15, 23, 42, 0.08);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.55;
}
button, a { font: inherit; }
.app-shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
}
.app-shell-single {
  display: block;
}
.side-nav {
  position: sticky;
  top: 0;
  height: 100vh;
  padding: 24px 16px;
  background: #111827;
  color: #e5e7eb;
}
.brand {
  font-size: 18px;
  font-weight: 750;
  letter-spacing: 0;
  margin-bottom: 18px;
}
.nav-link {
  display: block;
  color: #cbd5e1;
  text-decoration: none;
  padding: 9px 10px;
  border-radius: 6px;
  margin: 3px 0;
}
.nav-link:hover { background: rgba(255, 255, 255, 0.08); color: #fff; }
.report-main { min-width: 0; }
.top-bar {
  position: sticky;
  top: 0;
  z-index: 3;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 28px;
  background: rgba(255, 255, 255, 0.92);
  border-bottom: 1px solid var(--line);
  backdrop-filter: blur(12px);
}
.report-title { margin: 0; font-size: 21px; line-height: 1.2; }
.report-meta { color: var(--muted); font-size: 13px; margin-top: 4px; }
.header-tools { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }
.gate-pill {
  display: inline-flex;
  align-items: center;
  min-height: 30px;
  padding: 5px 10px;
  border-radius: 999px;
  background: #ecfdf3;
  color: #067647;
  font-size: 13px;
  font-weight: 700;
}
.gate-pill[data-status="BLOCK"] { background: #fef3f2; color: #b42318; }
.export-button {
  border: 1px solid #111827;
  background: #111827;
  color: #fff;
  border-radius: 6px;
  padding: 8px 12px;
  cursor: pointer;
}
.export-button:hover { background: #344054; }
.content { width: min(1180px, 100%); margin: 0 auto; padding: 26px 28px 56px; }
.report-section {
  margin: 0 0 24px;
  padding: 22px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  box-shadow: var(--shadow);
}
.section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}
.section-heading h2,
.section-title {
  margin: 0;
  font-size: 19px;
  line-height: 1.25;
}
.eyebrow {
  margin: 0 0 4px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}
.status-pill,
.chip {
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  padding: 4px 9px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: #eef6f5;
  color: var(--accent-strong);
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}
.chip-position { background: #eff6ff; color: var(--blue); }
.chip-watch { background: #f1f5f9; color: #475569; }
.chip-risk { background: #fef2f2; color: var(--red); }
.chip-action { background: #fff7ed; color: var(--amber); }
.today-script { border-top: 4px solid var(--accent); }
.script-hero {
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}
.script-badge {
  display: grid;
  place-items: center;
  min-height: 112px;
  padding: 16px;
  border: 1px solid #99d5cc;
  border-radius: 8px;
  background: #ecfdf5;
  color: var(--accent-strong);
  font-size: 22px;
  font-weight: 800;
  text-align: center;
}
.script-hero h3 {
  margin: 0 0 8px;
  font-size: 22px;
  line-height: 1.35;
}
.script-hero p { margin: 0 0 14px; color: #334155; }
.script-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.script-grid div,
.metric-card,
.detail-box,
.compact-detail,
.playbook-details,
.level-table {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel-soft);
}
.script-grid div { padding: 12px; }
.script-grid strong { display: block; margin-bottom: 4px; color: var(--text); }
.script-grid span { color: #475569; font-size: 13px; }
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
.market-thermometer .kpi-grid { margin-top: 4px; }
.kpi-card,
.metric-card {
  min-height: 112px;
  padding: 14px;
}
.kpi-label { color: var(--muted); font-size: 12px; }
.kpi-value { margin-top: 8px; font-size: 18px; font-weight: 760; }
.kpi-note { margin-top: 8px; color: var(--muted); font-size: 13px; }
.evidence-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.evidence-item {
  padding: 14px;
  border-left: 3px solid var(--accent);
  background: var(--panel-soft);
}
.action-groups {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
.action-group {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px;
  background: var(--panel-soft);
}
.action-group h3 { margin: 0 0 10px; font-size: 15px; }
.action-list { margin: 0; padding-left: 18px; color: #344054; }
.action-list li { margin: 7px 0; }
.action-matrix .matrix-wrap {
  overflow-x: auto;
  border: 1px solid var(--line);
  border-radius: 8px;
}
.matrix-wrap table {
  width: 100%;
  min-width: 760px;
  border-collapse: collapse;
  background: #fff;
  font-size: 13px;
}
.matrix-wrap th,
.matrix-wrap td {
  border-bottom: 1px solid var(--line);
  padding: 11px 10px;
  text-align: left;
  vertical-align: top;
}
.matrix-wrap th {
  color: var(--muted);
  background: #f8fafc;
  font-weight: 750;
}
.matrix-wrap tr:last-child td { border-bottom: 0; }
.empty-cell { color: var(--muted); text-align: center; }
.stock-grid { display: grid; gap: 16px; }
.stock-card {
  display: grid;
  gap: 14px;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel-soft);
}
.stock-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 14px;
}
.stock-card h3 { margin: 0; font-size: 18px; line-height: 1.25; }
.stock-card-tags { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.stock-card-layout {
  display: grid;
  grid-template-columns: minmax(560px, 1.9fr) minmax(320px, 1fr);
  gap: 18px;
  align-items: start;
}
.chart-panel { min-width: 0; }
.chart-frame {
  position: relative;
  min-height: 430px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
}
.chart-image-button {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  min-height: 430px;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: zoom-in;
}
.chart-frame img {
  display: block;
  width: 100%;
  height: auto;
  object-fit: contain;
}
.chart-empty { color: var(--muted); padding: 24px; text-align: center; }
.chart-note,
.price-rail-note {
  margin: 8px 0 0;
  color: var(--muted);
  font-size: 12px;
}
.chart-zoom-button {
  position: absolute;
  right: 12px;
  bottom: 12px;
  border: 1px solid rgba(15, 23, 42, 0.15);
  border-radius: 6px;
  padding: 7px 10px;
  background: rgba(17, 24, 39, 0.88);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  cursor: zoom-in;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.22);
}
.chart-zoom-button:hover { background: #111827; }
.stock-insight-panel {
  display: grid;
  gap: 10px;
  min-width: 0;
}
.detail-stack { display: grid; gap: 10px; }
.detail-box,
.compact-detail {
  background: #fff;
  padding: 12px;
}
.compact-primary {
  border-left: 4px solid var(--accent);
  background: #f0fdfa;
}
.detail-label { color: var(--muted); font-size: 12px; margin-bottom: 4px; }
.detail-value { font-weight: 650; }
.condition-list {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.condition-list li {
  display: grid;
  grid-template-columns: 54px minmax(0, 1fr);
  gap: 8px;
  align-items: start;
}
.condition-list strong { color: var(--text); font-size: 12px; }
.condition-list span { color: #475569; font-size: 13px; }
.level-table {
  display: grid;
  gap: 0;
  overflow: hidden;
  background: #fff;
}
.level-table-row {
  display: grid;
  grid-template-columns: minmax(72px, 0.95fr) minmax(64px, 0.8fr) minmax(80px, 1fr) minmax(98px, 1.2fr);
  gap: 8px;
  padding: 9px 10px;
  border-bottom: 1px solid var(--line);
  align-items: center;
}
.level-table-row:last-child { border-bottom: 0; }
.level-table span { color: var(--muted); font-size: 12px; }
.level-table strong { color: var(--text); font-size: 13px; }
.level-table em {
  color: #475569;
  font-style: normal;
  font-size: 12px;
}
.playbook-details {
  overflow: hidden;
  background: #fff;
}
.playbook-details > summary {
  cursor: pointer;
  list-style: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 11px 12px;
  color: var(--text);
  font-weight: 700;
}
.playbook-details > summary::-webkit-details-marker { display: none; }
.playbook-body {
  padding: 0 12px 12px;
  color: #475569;
  font-size: 13px;
}
.chart-lightbox {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: none;
  align-items: center;
  justify-content: center;
  padding: 28px;
  background: rgba(15, 23, 42, 0.88);
}
.chart-lightbox.is-open { display: flex; }
.chart-lightbox img {
  max-width: min(1280px, 96vw);
  max-height: 90vh;
  width: auto;
  height: auto;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 22px 60px rgba(0, 0, 0, 0.35);
}
.chart-lightbox-close {
  position: absolute;
  top: 18px;
  right: 18px;
  border: 1px solid rgba(255, 255, 255, 0.28);
  border-radius: 6px;
  padding: 8px 12px;
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
  cursor: pointer;
}
body.lightbox-open,
.lightbox-open {
  overflow: hidden;
}
.collapsible {
  padding: 0;
  overflow: hidden;
}
.collapsible > summary {
  cursor: pointer;
  list-style: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 18px 22px;
}
.collapsible > summary::-webkit-details-marker { display: none; }
.collapsible > summary small {
  display: block;
  margin-bottom: 4px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}
.collapsible > summary strong {
  display: block;
  color: var(--text);
  font-size: 19px;
  line-height: 1.25;
}
.summary-caret {
  color: var(--muted);
  font-size: 12px;
  white-space: nowrap;
}
.summary-caret::after {
  content: " +";
  font-weight: 800;
}
.collapsible[open] .summary-caret::after { content: " -"; }
.collapsible-body {
  padding: 0 22px 22px;
}
.appendix-note {
  margin-bottom: 12px;
  color: #475569;
}
.action-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.action-table th, .action-table td {
  border-bottom: 1px solid var(--line);
  padding: 10px 8px;
  text-align: left;
  vertical-align: top;
}
.action-table th { color: var(--muted); background: var(--panel-soft); }
.data-block {
  margin: 0;
  padding: 14px;
  overflow: auto;
  background: #101828;
  color: #e5e7eb;
  border-radius: 8px;
  font-size: 12px;
}
@media (max-width: 920px) {
  .app-shell { grid-template-columns: 1fr; }
  .side-nav {
    position: relative;
    height: auto;
    display: flex;
    gap: 8px;
    overflow-x: auto;
    align-items: center;
  }
  .brand { margin: 0 8px 0 0; flex: 0 0 auto; }
  .nav-link { flex: 0 0 auto; margin: 0; }
  .top-bar { position: relative; align-items: flex-start; flex-direction: column; }
  .kpi-grid, .evidence-grid, .action-groups, .stock-card, .script-hero, .script-grid { grid-template-columns: 1fr; }
  .stock-card-layout { grid-template-columns: 1fr; }
  .chart-frame, .chart-image-button { min-height: 360px; }
  .script-badge { min-height: 72px; }
  .content { padding: 18px 14px 42px; }
}
@media (max-width: 640px) {
  .report-section { padding: 16px; }
  .collapsible { padding: 0; }
  .collapsible > summary { padding: 16px; }
  .collapsible-body { padding: 0 16px 16px; }
  .stock-card { padding: 12px; }
  .stock-card-header { flex-direction: column; align-items: stretch; }
  .stock-card-tags { justify-content: flex-start; }
  .chart-frame, .chart-image-button { min-height: 280px; }
  .condition-list li { grid-template-columns: 1fr; }
  .level-table-row { grid-template-columns: 1fr 0.8fr; }
  .level-table-row em { grid-column: 1 / -1; }
}
@media print {
  body { background: #fff; }
  .side-nav, .export-button, .chart-zoom-button, .chart-lightbox { display: none !important; }
  .app-shell { display: block; }
  .top-bar { position: relative; border-bottom: 1px solid #ddd; }
  .content { width: 100%; padding: 16px 0; }
  .report-section, .stock-card { break-inside: avoid; box-shadow: none; }
  .stock-card-layout { grid-template-columns: 1fr; }
  .collapsible > summary { break-after: avoid; }
  .playbook-details > summary { break-after: avoid; }
  details.collapsible:not([open]) > .collapsible-body { display: block; }
  details.playbook-details:not([open]) > .playbook-body { display: block; }
  .chart-frame, .chart-image-button { min-height: 360px; }
  .chart-frame img { max-height: 500px; }
}
"""

HTML_REPORT_JS = """
function openCollapsibleSectionsForExport() {
  document.querySelectorAll("details.collapsible").forEach(function(section) {
    section.setAttribute("open", "");
  });
}

function openPlaybooksForExport() {
  document.querySelectorAll("details.playbook-details").forEach(function(section) {
    section.setAttribute("open", "");
  });
}

function openChartLightbox(button) {
  var frame = button && button.closest ? button.closest(".chart-frame") : null;
  var sourceImage = frame ? frame.querySelector("img") : null;
  var lightbox = document.getElementById("chart-lightbox");
  var targetImage = document.getElementById("chart-lightbox-image");
  if (!sourceImage || !lightbox || !targetImage) {
    return;
  }
  targetImage.src = sourceImage.src;
  targetImage.alt = sourceImage.alt || "K 线图";
  lightbox.classList.add("is-open");
  lightbox.setAttribute("aria-hidden", "false");
  document.body.classList.add("lightbox-open");
}

function closeChartLightbox() {
  var lightbox = document.getElementById("chart-lightbox");
  var targetImage = document.getElementById("chart-lightbox-image");
  if (lightbox) {
    lightbox.classList.remove("is-open");
    lightbox.setAttribute("aria-hidden", "true");
  }
  if (targetImage) {
    targetImage.removeAttribute("src");
  }
  document.body.classList.remove("lightbox-open");
}

document.addEventListener("keydown", function(event) {
  if (event.key === "Escape") {
    closeChartLightbox();
  }
});

function exportPdf() {
  openCollapsibleSectionsForExport();
  openPlaybooksForExport();
  window.print();
}
"""
NON_CONTEXT_VALUES = {"", "PASS", "WARN", "BLOCK", "UNKNOWN", "未知"}


class JsonCliError(Exception):
    """Raised for CLI usage errors that should be printed as JSON."""


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise JsonCliError(message)

    def exit(self, status: int = 0, message: Optional[str] = None) -> None:
        if status:
            raise JsonCliError((message or f"exit status {status}").strip())
        raise SystemExit(status)


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _stock_label(item: dict[str, Any]) -> str:
    name = item.get("name")
    code = _code_key(item.get("code"))
    if name and code:
        return f"{name}（{code}）"
    return str(name or code or "未知")


def _format_ratio(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _format_number(value: Any, digits: int = 2) -> str:
    number = _as_float(value)
    if number is None:
        return "未知"
    return f"{number:.{digits}f}".rstrip("0").rstrip(".")


def _format_signed_number(value: Any, digits: int = 2) -> str:
    number = _as_float(value)
    if number is None:
        return "未知"
    sign = "+" if number > 0 else ""
    return f"{sign}{_format_number(number, digits)}"


def _format_pct(value: Any) -> str:
    number = _as_float(value)
    if number is None:
        return "未知"
    percentage = number * 100 if abs(number) <= 1 else number
    return f"{percentage:.2f}".rstrip("0").rstrip(".") + "%"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _inline_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _md_cell(value: Any) -> str:
    normalized = str(value).replace("\n", " ")
    return html.escape(normalized, quote=False).replace("|", "\\|")


def _md_text(value: Any) -> str:
    normalized = "".join(" " if char in "\r\n\t" or ord(char) < 32 else char for char in str(value))
    escaped = html.escape(normalized, quote=False)
    markdown_chars = "\\`*_{}[]()#+-.!|"
    return "".join(f"\\{char}" if char in markdown_chars else char for char in escaped)


def _html(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _code_key(value: Any) -> str:
    return str(value or "").strip()


def _compact_security_item(item: Any) -> Any:
    if not isinstance(item, dict):
        return item

    compact: dict[str, Any] = {}
    for key in ("code", "name", "close", "price", "ma20", "ma40", "source"):
        if key in item:
            compact[key] = item[key]

    indicators = item.get("indicators")
    if isinstance(indicators, dict):
        for key in ("ma20", "ma40"):
            if key not in compact and key in indicators:
                compact[key] = indicators[key]

    rows = item.get("rows")
    if "close" not in compact and isinstance(rows, list) and rows:
        latest = rows[-1]
        if isinstance(latest, dict) and "close" in latest:
            compact["close"] = latest["close"]

    fallback = item.get("fallback_from")
    if isinstance(fallback, dict) and fallback.get("source"):
        compact["fallback_from"] = fallback.get("source")

    return compact or item


def _compact_group(group: Any) -> Any:
    if not isinstance(group, dict):
        return group

    compact: dict[str, Any] = {}
    for key in (
        "status",
        "source",
        "environment",
        "stance",
        "stage",
        "trade_date",
        "limit_up_count",
        "break_board_rate",
        "height",
        "leader_performance",
        "reason",
        "missing",
    ):
        if key in group:
            compact[key] = group[key]

    items = group.get("items")
    if isinstance(items, list):
        compact["items"] = [_compact_security_item(item) for item in items]

    return compact


def odds(price: Any, target: Any, stop: Any) -> float:
    """Return upside/downside odds rounded to two decimals, or 0 for invalid input."""
    price_value = _as_float(price)
    target_value = _as_float(target)
    stop_value = _as_float(stop)
    if price_value is None or target_value is None or stop_value is None:
        return 0.0

    upside = target_value - price_value
    downside = price_value - stop_value
    if downside <= 0 or upside <= 0:
        return 0.0
    return round(upside / downside, 2)


def position_action(item: dict[str, Any]) -> dict[str, str]:
    close = _as_float(item.get("close", item.get("price")))
    ma20 = _as_float(item.get("ma20"))
    ma40 = _as_float(item.get("ma40"))
    stock = _stock_label(item)

    if close is not None and ma40 is not None and close < ma40:
        return {
            "bucket": "必须执行",
            "stock": stock,
            "action": "退出",
            "text": f"{stock}：收盘跌破 MA40，趋势纪律触发；次日开盘一次性退出。",
        }

    if close is not None and ma20 is not None and close < ma20:
        return {
            "bucket": "条件执行",
            "stock": stock,
            "action": "减仓",
            "text": f"{stock}：收盘跌破 MA20，先减仓；若 1-2 日不能快速收回 MA20，继续降风险，严禁补仓。",
        }

    return {
        "bucket": "观察等待",
        "stock": stock,
        "action": "持有",
        "text": f"{stock}：持有观察，执行 MA20/MA40 纪律；跌破 MA20 减仓，跌破 MA40 退出。",
    }


def _minimum_odds_ratio(snapshot: dict[str, Any]) -> float:
    risk = _preferences(snapshot).get("risk", {})
    ratio = _as_float(risk.get("minimum_odds_ratio") if isinstance(risk, dict) else None)
    return ratio if ratio is not None and ratio > 0 else 2.0


def _context_value(data: dict[str, Any], keys: tuple[str, ...]) -> Optional[str]:
    for key in keys:
        value = str(data.get(key) or "").strip()
        if value and value.upper() not in NON_CONTEXT_VALUES and value not in NON_CONTEXT_VALUES:
            return value
    return None


def _market_context_known(market: dict[str, Any]) -> bool:
    return _context_value(market, ("environment", "stance", "stage")) is not None


def _emotion_context_known(emotion: dict[str, Any]) -> bool:
    return _context_value(emotion, ("stage",)) is not None


def _market_blocks_new_buy(market: dict[str, Any]) -> bool:
    text = " ".join(str(market.get(key, "")) for key in ("environment", "stance", "stage"))
    return any(word in text for word in ("减量", "防守"))


def _emotion_blocks_new_buy(emotion: dict[str, Any]) -> bool:
    text = " ".join(str(emotion.get(key, "")) for key in ("stage",))
    return any(word in text for word in ("高潮", "退潮"))


def watch_action(
    item: dict[str, Any],
    minimum_odds_ratio: float = 2.0,
    market: Optional[dict[str, Any]] = None,
    emotion: Optional[dict[str, Any]] = None,
) -> dict[str, str]:
    stock = _stock_label(item)
    return {
        "bucket": "观察等待",
        "stock": stock,
        "action": "技术跟踪",
        "trigger": "支撑/压力/均线",
        "position": "只做技术跟踪",
        "text": f"{stock}：技术跟踪；趋势观察；{_trend_status_text(item)}；{_support_pressure_text(item, include_trade_plan_levels=False)}",
    }


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _snapshot_items(snapshot: dict[str, Any], key: str) -> list[dict[str, Any]]:
    top_level = snapshot.get(key)
    if isinstance(top_level, list):
        return [dict(item) for item in top_level if isinstance(item, dict)]

    state = snapshot.get("state")
    if isinstance(state, dict):
        nested = state.get(key)
        if isinstance(nested, list):
            return [dict(item) for item in nested if isinstance(item, dict)]
    return []


def _latest_close(stock_item: dict[str, Any]) -> Optional[float]:
    rows = stock_item.get("rows")
    if not isinstance(rows, list) or not rows:
        return None
    latest = rows[-1]
    if not isinstance(latest, dict):
        return None
    return _as_float(latest.get("close"))


def _security_rows(item: dict[str, Any]) -> list[dict[str, Any]]:
    rows = item.get("rows")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _close_value(item: dict[str, Any]) -> Optional[float]:
    for key in ("close", "price"):
        value = _as_float(item.get(key))
        if value is not None:
            return value
    return _latest_close(item)


def _rolling_average(values: list[float], period: int) -> list[float]:
    averages: list[float] = []
    for index in range(len(values)):
        if index + 1 < period:
            averages.append(float("nan"))
            continue
        window = values[index + 1 - period : index + 1]
        averages.append(round(sum(window) / period, 4))
    return averages


def _indicator_value(item: dict[str, Any], key: str) -> Optional[float]:
    direct = _as_float(item.get(key))
    if direct is not None:
        return direct

    indicators = item.get("indicators")
    if isinstance(indicators, dict):
        value = _as_float(indicators.get(key))
        if value is not None:
            return value

    period_text = key.removeprefix("ma")
    if not period_text.isdigit():
        return None
    period = int(period_text)
    closes = [_as_float(row.get("close")) for row in _security_rows(item)]
    clean_closes = [value for value in closes if value is not None]
    if len(clean_closes) < period:
        return None
    return round(sum(clean_closes[-period:]) / period, 4)


def _ohlcv_rows(item: dict[str, Any], limit: int = 90) -> list[dict[str, Any]]:
    candles: list[dict[str, Any]] = []
    for row in _security_rows(item)[-limit:]:
        open_value = _as_float(row.get("open"))
        high = _as_float(row.get("high"))
        low = _as_float(row.get("low"))
        close = _as_float(row.get("close"))
        if open_value is None or high is None or low is None or close is None:
            continue
        candles.append(
            {
                "date": str(row.get("date") or ""),
                "open": open_value,
                "high": high,
                "low": low,
                "close": close,
                "volume": _as_float(row.get("volume")) or 0.0,
            }
        )
    return candles


def _empty_level(source: str = "unknown") -> dict[str, Any]:
    return {"value": None, "low": None, "high": None, "confidence": "low", "source": source, "touches": 0}


def _hard_stop_value(item: dict[str, Any]) -> Optional[float]:
    for key in ("stop", "stop_price", "hard_stop"):
        value = _as_float(item.get(key))
        if value is not None:
            return value
    position = item.get("position")
    if isinstance(position, dict):
        for key in ("stop", "stop_price", "hard_stop"):
            value = _as_float(position.get(key))
            if value is not None:
                return value
    return None


def _level_display_label(kind: str) -> str:
    return {
        "resistance": "上方压力",
        "price": "当前价",
        "support": "下方支撑",
        "stop": "硬止损",
    }.get(kind, kind)


def _level_source_label(source: str) -> str:
    if source.startswith("ma") and source[2:].isdigit():
        return f"MA{source[2:]} 动态位"
    return {
        "price": "最新收盘",
        "swing_high": "前高密集区",
        "swing_low": "前低密集区",
        "target": "目标价",
        "hard_stop": "账户纪律",
    }.get(source, source)


def _level_distance_pct(value: Optional[float], price: Optional[float]) -> Optional[float]:
    if value is None or price in (None, 0):
        return None
    return (value - price) / price * 100


def _make_price_level(
    *,
    kind: str,
    value: Optional[float],
    price: Optional[float],
    source: str,
    confidence: str,
    is_dynamic: bool = False,
    band_low: Optional[float] = None,
    band_high: Optional[float] = None,
) -> Optional[dict[str, Any]]:
    if value is None:
        return None
    numeric_value = float(value)
    level = {
        "kind": kind,
        "display_label": _level_display_label(kind),
        "value": round(numeric_value, 2),
        "source": source,
        "source_label": _level_source_label(source),
        "confidence": confidence,
        "distance_pct": _level_distance_pct(numeric_value, price),
        "is_dynamic": is_dynamic,
    }
    if not is_dynamic:
        if band_low is not None:
            level["band_low"] = round(float(band_low), 2)
        if band_high is not None:
            level["band_high"] = round(float(band_high), 2)
    return level


def _level_band(value: float, values: list[float]) -> tuple[float, float]:
    span = max(values) - min(values) if values else 0.0
    width = max(abs(value) * 0.006, span * 0.018, 0.01)
    return round(value - width, 4), round(value + width, 4)


def _cluster_price_levels(values: list[float], source: str = "swing") -> list[dict[str, Any]]:
    clean_values = sorted(float(value) for value in values if value is not None and value > 0)
    clusters: list[list[float]] = []
    for value in clean_values:
        if not clusters:
            clusters.append([value])
            continue
        anchor = sum(clusters[-1]) / len(clusters[-1])
        tolerance = max(abs(anchor) * 0.012, 0.02)
        if abs(value - anchor) <= tolerance:
            clusters[-1].append(value)
        else:
            clusters.append([value])

    levels = []
    for cluster in clusters:
        value = round(sum(cluster) / len(cluster), 4)
        low, high = _level_band(value, clean_values)
        touches = len(cluster)
        confidence = "high" if touches >= 3 else "medium" if touches >= 2 else "low"
        levels.append(
            {
                "value": value,
                "low": low,
                "high": high,
                "confidence": confidence,
                "source": source,
                "touches": touches,
            }
        )
    return levels


def _ma_level(item: dict[str, Any], window: int, price: Optional[float]) -> Optional[dict[str, Any]]:
    value = _indicator_value(item, f"ma{window}")
    if value is None:
        return None
    return _make_price_level(
        kind="support" if price is None or value <= price else "resistance",
        value=value,
        price=price,
        source=f"ma{window}",
        confidence="medium",
        is_dynamic=True,
    )


def _choose_level(
    candidates: list[dict[str, Any]], close: Optional[float], direction: str
) -> dict[str, Any]:
    if not candidates:
        return _empty_level(direction)
    if close is None:
        return max(candidates, key=lambda level: (level.get("touches", 0), level.get("value") or 0))

    if direction == "support":
        valid = [level for level in candidates if _as_float(level.get("value")) is not None and level["value"] <= close]
        if not valid:
            return _empty_level(direction)
        repeated = [level for level in valid if int(level.get("touches") or 0) >= 2]
        pool = repeated or valid
        return max(pool, key=lambda level: (level.get("value") if level.get("value") is not None else float("-inf")))

    valid = [level for level in candidates if _as_float(level.get("value")) is not None and level["value"] >= close]
    if not valid:
        return _empty_level(direction)
    repeated = [level for level in valid if int(level.get("touches") or 0) >= 2]
    pool = repeated or valid
    return min(pool, key=lambda level: (level.get("value") if level.get("value") is not None else float("inf")))


def _support_resistance_levels(
    item: dict[str, Any],
    *,
    include_target: bool = True,
    include_stop: bool = True,
) -> dict[str, dict[str, Any]]:
    candles = _ohlcv_rows(item, limit=90)
    recent = candles[-60:] if candles else []
    close = _close_value(item)
    lows = [candle["low"] for candle in recent]
    highs = [candle["high"] for candle in recent]
    price_values = lows + highs

    support_candidates = _cluster_price_levels(lows, "swing_low")
    resistance_candidates = _cluster_price_levels(highs, "swing_high")

    target = _as_float(item.get("target")) if include_target else None
    if target is not None and (close is None or target >= close):
        low, high = _level_band(target, price_values or [target])
        resistance_candidates.append(
            {
                "value": round(target, 4),
                "low": low,
                "high": high,
                "confidence": "medium",
                "source": "target",
                "touches": 1,
            }
        )

    stop = _hard_stop_value(item) if include_stop else None
    hard_stop = _empty_level("hard_stop" if include_stop else "unknown")
    if stop is not None:
        low, high = _level_band(stop, price_values or [stop])
        hard_stop = {
            "value": round(stop, 4),
            "low": low,
            "high": high,
            "confidence": "hard",
            "source": "hard_stop",
            "touches": 1,
        }

    return {
        "support": _choose_level(support_candidates, close, "support"),
        "resistance": _choose_level(resistance_candidates, close, "resistance"),
        "pressure": _choose_level(resistance_candidates, close, "resistance"),
        "hard_stop": hard_stop,
    }


def _price_level_ladder(
    item: dict[str, Any],
    *,
    include_target: bool = True,
    include_stop: bool = True,
) -> list[dict[str, Any]]:
    price = _close_value(item)
    ladder: list[dict[str, Any]] = []
    rows = _ohlcv_rows(item)
    swing_levels = _support_resistance_levels(item, include_target=include_target, include_stop=include_stop)

    pressure = swing_levels.get("pressure") or swing_levels.get("resistance") or {}
    support = swing_levels.get("support") or {}
    hard_stop = swing_levels.get("hard_stop") or {}

    pressure_level = _make_price_level(
        kind="resistance",
        value=pressure.get("value"),
        price=price,
        source=pressure.get("source", "swing_high"),
        confidence=pressure.get("confidence", "medium"),
        band_low=pressure.get("low"),
        band_high=pressure.get("high"),
    )
    if pressure_level:
        ladder.append(pressure_level)

    price_level = _make_price_level(
        kind="price",
        value=price,
        price=price,
        source="price",
        confidence="live",
        is_dynamic=True,
    )
    if price_level:
        ladder.append(price_level)

    for window in (5, 10, 20, 40):
        level = _ma_level(item, window, price)
        if level:
            ladder.append(level)

    support_level = _make_price_level(
        kind="support",
        value=support.get("value"),
        price=price,
        source=support.get("source", "swing_low"),
        confidence=support.get("confidence", "medium"),
        band_low=support.get("low"),
        band_high=support.get("high"),
    )
    if support_level:
        ladder.append(support_level)

    if include_stop:
        stop_level = _make_price_level(
            kind="stop",
            value=hard_stop.get("value"),
            price=price,
            source="hard_stop",
            confidence="hard",
            is_dynamic=True,
        )
        if stop_level:
            ladder.append(stop_level)

    if rows:
        recent_low = min(row["low"] for row in rows[-20:])
        recent_high = max(row["high"] for row in rows[-20:])
        if price:
            if recent_low <= price and not any(level["kind"] == "support" and level["source"] == "swing_low" for level in ladder):
                fallback_support = _make_price_level(
                    kind="support",
                    value=recent_low,
                    price=price,
                    source="swing_low",
                    confidence="low",
                    band_low=recent_low,
                    band_high=recent_low,
                )
                if fallback_support:
                    ladder.append(fallback_support)
            if recent_high >= price and not any(level["kind"] == "resistance" and level["source"] == "swing_high" for level in ladder):
                fallback_pressure = _make_price_level(
                    kind="resistance",
                    value=recent_high,
                    price=price,
                    source="swing_high",
                    confidence="low",
                    band_low=recent_high,
                    band_high=recent_high,
                )
                if fallback_pressure:
                    ladder.append(fallback_pressure)

    seen: set[tuple[str, str, float]] = set()
    deduped: list[dict[str, Any]] = []
    for level in ladder:
        key = (level["kind"], level["source"], round(float(level["value"]), 2))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(level)
    return sorted(deduped, key=lambda level: float(level["value"]), reverse=True)


def _recent_support_pressure(
    item: dict[str, Any],
    *,
    include_trade_plan_levels: bool = True,
) -> tuple[Optional[float], Optional[float]]:
    price = _close_value(item)
    ladder = _price_level_ladder(
        item,
        include_target=include_trade_plan_levels,
        include_stop=include_trade_plan_levels,
    )
    supports = [level for level in ladder if level.get("kind") == "support"]
    pressures = [level for level in ladder if level.get("kind") == "resistance"]

    if price is not None:
        below = [level for level in supports if _as_float(level.get("value")) is not None and level["value"] <= price]
        above = [level for level in pressures if _as_float(level.get("value")) is not None and level["value"] >= price]
        support_level = max(below, key=lambda level: level["value"], default=supports[0] if supports else None)
        pressure_level = min(above, key=lambda level: level["value"], default=pressures[0] if pressures else None)
    else:
        support_level = supports[0] if supports else None
        pressure_level = pressures[0] if pressures else None
    support_value = _as_float(support_level.get("value")) if support_level else None
    pressure_value = _as_float(pressure_level.get("value")) if pressure_level else None
    return support_value, pressure_value




def _stock_data_by_code(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    stocks = snapshot.get("stocks")
    if not isinstance(stocks, dict):
        return {}

    indexed: dict[str, dict[str, Any]] = {}
    for item in _as_list(stocks.get("items")):
        if not isinstance(item, dict):
            continue
        code = item.get("code")
        if code is None:
            continue
        merged: dict[str, Any] = {}
        for key in ("code", "name", "source", "fallback_from"):
            if key in item:
                merged[key] = item[key]
        rows = _security_rows(item)
        if rows:
            merged["rows"] = rows
        close = _as_float(item.get("close"))
        if close is None:
            close = _latest_close(item)
        if close is not None:
            merged["close"] = close
            merged["price"] = close
        for key in ("ma20", "ma40"):
            direct = _as_float(item.get(key))
            if direct is not None:
                merged[key] = direct
        indicators = item.get("indicators")
        if isinstance(indicators, dict):
            merged["indicators"] = dict(indicators)
            for key in ("ma20", "ma40"):
                if key in indicators and key not in merged:
                    merged[key] = indicators[key]
        code_key = _code_key(code)
        if code_key:
            indexed[code_key] = merged
    return indexed


def _merge_stock_data(items: list[dict[str, Any]], stock_data: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    merged_items: list[dict[str, Any]] = []
    for item in items:
        merged = dict(item)
        code = item.get("code")
        if code is not None:
            for key, value in stock_data.get(_code_key(code), {}).items():
                merged.setdefault(key, value)
        merged_items.append(merged)
    return merged_items


def _preferences(snapshot: dict[str, Any]) -> dict[str, Any]:
    direct = snapshot.get("preferences")
    if isinstance(direct, dict):
        return direct
    state = snapshot.get("state")
    if isinstance(state, dict) and isinstance(state.get("preferences"), dict):
        return state["preferences"]
    return {}


def _reserve_cash_line(snapshot: dict[str, Any]) -> str:
    risk = _preferences(snapshot).get("risk", {})
    reserve = _as_float(risk.get("reserve_cash_ratio") if isinstance(risk, dict) else None)
    if reserve is None:
        reserve = 0.2
    percentage = reserve * 100 if reserve <= 1 else reserve
    return f"至少保留 {_format_ratio(round(percentage, 2))}% 现金；未出现清晰技术确认时不动用预备队"


def _market_environment(market: dict[str, Any]) -> str:
    return _context_value(market, ("environment", "stance", "stage")) or "未知"


def _emotion_stage(emotion: dict[str, Any]) -> str:
    return _context_value(emotion, ("stage",)) or "未知"


def _collect_actions(snapshot: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    stock_data = _stock_data_by_code(snapshot)
    positions = _merge_stock_data(_snapshot_items(snapshot, "positions"), stock_data)
    position_codes = {_code_key(item.get("code")) for item in positions if isinstance(item, dict) and _code_key(item.get("code"))}
    watchlist = _merge_stock_data(
        [item for item in _snapshot_items(snapshot, "watchlist") if _code_key(item.get("code")) not in position_codes],
        stock_data,
    )
    market = snapshot.get("market") if isinstance(snapshot.get("market"), dict) else {}
    emotion = snapshot.get("emotion") if isinstance(snapshot.get("emotion"), dict) else {}
    minimum_odds = _minimum_odds_ratio(snapshot)
    position_actions = [position_action(item) for item in positions]
    watch_actions = [watch_action(item, minimum_odds, market, emotion) for item in watchlist]
    return position_actions, watch_actions


def _append_summary(lines: list[str], actions: dict[str, list[str]]) -> None:
    for bucket in ACTION_BUCKETS:
        lines.append(f"### {ACTION_DISPLAY_NAMES.get(bucket, bucket)}")
        if actions[bucket]:
            lines.extend(f"- {text}" for text in actions[bucket])
        else:
            lines.append("- 无")
        lines.append("")


def _short_stock_list(actions: list[dict[str, str]], limit: int = 6) -> str:
    names = [_md_text(action.get("stock", "未知")) for action in actions]
    if len(names) <= limit:
        return "、".join(names)
    return "、".join(names[:limit]) + f" 等 {len(names)} 只"


def _append_execution_summary(
    lines: list[str], position_actions: list[dict[str, str]], watch_actions: list[dict[str, str]]
) -> None:
    for bucket in ACTION_BUCKETS:
        lines.append(f"### {ACTION_DISPLAY_NAMES.get(bucket, bucket)}")
        bucket_positions = [action for action in position_actions if action.get("bucket") == bucket]
        bucket_watch = [action for action in watch_actions if action.get("bucket") == bucket]
        if not bucket_positions and not bucket_watch:
            lines.append("- 无")
            lines.append("")
            continue

        for action_name in sorted({action.get("action", "") for action in bucket_positions}):
            group = [action for action in bucket_positions if action.get("action") == action_name]
            if len(group) == 1:
                lines.append(f"- {_md_text(group[0]['text'])}")
            else:
                lines.append(
                    f"- 持仓 {len(group)} 只：{_short_stock_list(group)}；统一动作：{action_name}，明细看“持仓诊断”。"
                )

        for action_name in sorted({action.get("action", "") for action in bucket_watch}):
            group = [action for action in bucket_watch if action.get("action") == action_name]
            if len(group) == 1:
                lines.append(f"- {_md_text(group[0]['text'])}")
            else:
                lines.append(
                    f"- 关注池 {len(group)} 只：{_short_stock_list(group)}；统一动作：{action_name}，明细看“关注池剧本”。"
                )
        lines.append("")


def _watch_position_size(action: dict[str, str]) -> str:
    action_name = action.get("action", "")
    bucket = action.get("bucket", "")
    if action_name == "条件买入":
        return "1/4 到 1/3 试探"
    if action_name == "禁止买入" or bucket == "禁止动作":
        return "禁止开仓/保留现金"
    if action_name in {"等待信号", "等待环境确认"} or bucket == "观察等待":
        return "保留现金"
    return "按信号处理"


def _append_action_table(lines: list[str], position_actions: list[dict[str, str]], watch_actions: list[dict[str, str]]) -> None:
    lines.extend(
        [
            "## 个股动作表",
            "",
            "| 股票 | 身份 | 结论 | 动作 | 触发位 | 仓位 | 理由 |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for action in position_actions:
        lines.append(
            "| {stock} | 持仓 | {bucket} | {action} | MA20/MA40 | 按纪律处理，不加破位仓 | {text} |".format(
                stock=_md_cell(action["stock"]),
                bucket=_md_cell(ACTION_DISPLAY_NAMES.get(action["bucket"], action["bucket"])),
                action=_md_cell(action["action"]),
                text=_md_cell(action["text"]),
            )
        )
    for action in watch_actions:
        lines.append(
            "| {stock} | 关注 | {bucket} | {action} | {trigger} | {size} | {text} |".format(
                stock=_md_cell(action["stock"]),
                bucket=_md_cell(ACTION_DISPLAY_NAMES.get(action["bucket"], action["bucket"])),
                action=_md_cell(action["action"]),
                trigger=_md_cell(action.get("trigger") or "支撑/压力/均线"),
                size=_md_cell(action.get("position") or "只做技术跟踪"),
                text=_md_cell(action["text"]),
            )
        )
    if not position_actions and not watch_actions:
        lines.append("| 无 | - | 观察等待 | 无 | - | 保留现金 | 今日无个股动作 |")
    lines.append("")


def _market_index_line(market: dict[str, Any]) -> str:
    items = [item for item in _as_list(market.get("items")) if isinstance(item, dict)]
    total = 0
    above_ma20 = 0
    above_ma40 = 0
    details: list[str] = []
    for item in items:
        close = _close_value(item)
        ma20 = _indicator_value(item, "ma20")
        ma40 = _indicator_value(item, "ma40")
        if close is None:
            continue
        total += 1
        if ma20 is not None and close >= ma20:
            above_ma20 += 1
        if ma40 is not None and close >= ma40:
            above_ma40 += 1
        label = _stock_label(item)
        if ma20 is not None and ma40 is not None:
            details.append(f"{label} 收盘 {_format_number(close)} / MA20 {_format_number(ma20)} / MA40 {_format_number(ma40)}")

    if total == 0:
        return "核心指数缺少可用 K 线，市场方向只能降级为观察。"

    prefix = f"{above_ma20}/{total} 个核心指数站上 MA20，{above_ma40}/{total} 个站上 MA40"
    if details:
        return f"{prefix}；" + "；".join(details[:3])
    return prefix


def _market_index_summary(market: dict[str, Any]) -> str:
    items = [item for item in _as_list(market.get("items")) if isinstance(item, dict)]
    total = 0
    above_ma20 = 0
    above_ma40 = 0
    for item in items:
        close = _close_value(item)
        ma20 = _indicator_value(item, "ma20")
        ma40 = _indicator_value(item, "ma40")
        if close is None:
            continue
        total += 1
        if ma20 is not None and close >= ma20:
            above_ma20 += 1
        if ma40 is not None and close >= ma40:
            above_ma40 += 1
    if total == 0:
        return "核心指数缺少有效样本"
    return f"{above_ma20}/{total} 站上 MA20，{above_ma40}/{total} 站上 MA40"


def _fund_flow_line(snapshot: dict[str, Any]) -> str:
    funds = snapshot.get("funds") if isinstance(snapshot.get("funds"), dict) else {}
    changes = []
    for item in _as_list(funds.get("items")):
        if isinstance(item, dict):
            value = _as_float(item.get("scale_change_billion"))
            if value is not None:
                changes.append(value)
    if not changes:
        return "ETF 规模变化缺少有效样本，资金方向需要降权。"
    total = sum(changes)
    return f"ETF 样本规模变化合计 {_format_signed_number(total)} 亿；正值表示被动资金继续补给，负值表示承接变弱。"


def _money_amount(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip()
    multiplier = 1.0
    if text.endswith("亿"):
        text = text[:-1]
    elif text.endswith("万"):
        text = text[:-1]
        multiplier = 0.0001
    number = _as_float(text)
    if number is None:
        return None
    return number * multiplier


def _sector_line(snapshot: dict[str, Any]) -> str:
    sectors = snapshot.get("sectors") if isinstance(snapshot.get("sectors"), dict) else {}
    items = [item for item in _as_list(sectors.get("items")) if isinstance(item, dict)]
    if not items:
        return "板块资金缺少有效样本，主战场暂不明确。"

    def sort_key(item: dict[str, Any]) -> float:
        value = _money_amount(item.get("main_net_inflow"))
        return value if value is not None else float("-inf")

    ranked = sorted(items, key=sort_key, reverse=True)[:3]
    parts = []
    for item in ranked:
        name = item.get("name", "未知板块")
        change = _format_number(item.get("change_pct"))
        inflow = item.get("main_net_inflow", "未知")
        parts.append(f"{name} 涨幅 {change}%，主力净流入 {inflow}")
    return "板块资金靠前：" + "；".join(parts)


def _sector_summary(snapshot: dict[str, Any]) -> str:
    sectors = snapshot.get("sectors") if isinstance(snapshot.get("sectors"), dict) else {}
    items = [item for item in _as_list(sectors.get("items")) if isinstance(item, dict)]
    names = [str(item.get("name")) for item in items[:3] if item.get("name")]
    return "、".join(names) if names else "主线暂不明确"


def _emotion_line(emotion: dict[str, Any]) -> str:
    limit_up = _format_number(emotion.get("limit_up_count"), 0)
    break_rate = _format_pct(emotion.get("break_board_rate"))
    height = _format_number(emotion.get("height"), 0)
    stage = _emotion_stage(emotion)
    leader = emotion.get("leader_performance")
    text = f"涨停 {limit_up} 家，炸板率 {break_rate}，连板高度 {height}，情绪阶段 {stage}"
    if leader:
        text += f"；{leader}"
    return text


def _emotion_summary(emotion: dict[str, Any]) -> str:
    return (
        f"涨停 {_format_number(emotion.get('limit_up_count'), 0)} 家，"
        f"炸板率 {_format_pct(emotion.get('break_board_rate'))}，"
        f"高度 {_format_number(emotion.get('height'), 0)}，"
        f"{_emotion_stage(emotion)}"
    )


def _market_inference(snapshot: dict[str, Any]) -> str:
    market = snapshot.get("market") if isinstance(snapshot.get("market"), dict) else {}
    emotion = snapshot.get("emotion") if isinstance(snapshot.get("emotion"), dict) else {}
    stage = _emotion_stage(emotion)
    environment = _market_environment(market)

    if "退潮" in stage:
        return "情绪退潮优先保护本金，新开仓只允许等待缩量止跌和重新转强后的右侧确认。"
    if "高潮" in stage:
        return "赚钱效应强但追高波动加大，持仓按趋势纪律拿，关注池只记录回踩确认、重新突破和趋势转弱位置。"
    if any(word in environment for word in ("进攻", "增量", "启动", "扩散")):
        return "环境允许关注主线内的右侧结构，但关注池仍只跟踪支撑、压力、均线和量价确认。"
    if any(word in environment for word in ("防守", "减量")):
        return "资金环境偏防守，先处理破位和弱势票，关注池只保留低位企稳和趋势修复观察。"
    return "市场方向尚未给出强确认，以观察和纪律执行为主，不因为单只股票波动提前放大仓位。"


def _append_market_evidence(lines: list[str], snapshot: dict[str, Any]) -> None:
    market = snapshot.get("market") if isinstance(snapshot.get("market"), dict) else {}
    emotion = snapshot.get("emotion") if isinstance(snapshot.get("emotion"), dict) else {}
    lines.extend(
        [
            "## 市场证据链",
            "",
            f"- 指数结构：{_market_index_line(market)}",
            f"- 资金供给：{_fund_flow_line(snapshot)}",
            f"- 板块主线：{_sector_line(snapshot)}",
            f"- 情绪温度：{_emotion_line(emotion)}",
            f"- 综合推断：{_market_inference(snapshot)}",
            "",
        ]
    )


def _trend_status_text(item: dict[str, Any]) -> str:
    close = _close_value(item)
    ma20 = _indicator_value(item, "ma20")
    ma40 = _indicator_value(item, "ma40")
    if close is None:
        return "缺少最新收盘价，当前结构只能按数据不足处理。"
    if ma20 is None or ma40 is None:
        return f"现价 {_format_number(close)}，但 MA20/MA40 不完整，趋势判断降级为观察。"
    if close >= ma20 and close >= ma40:
        if ma20 >= ma40:
            return f"现价 {_format_number(close)} 位于 MA20 {_format_number(ma20)} 和 MA40 {_format_number(ma40)} 上方，短中期结构偏强。"
        return f"现价 {_format_number(close)} 已站上 MA20 {_format_number(ma20)} 和 MA40 {_format_number(ma40)}，但 MA20 仍低于 MA40，属于反弹修复，需看回踩确认。"
    if close >= ma20 and close < ma40:
        return f"现价 {_format_number(close)} 站上 MA20 {_format_number(ma20)}，但仍低于 MA40 {_format_number(ma40)}，属于修复未完成。"
    if close < ma20 and close >= ma40:
        return f"现价 {_format_number(close)} 跌破 MA20 {_format_number(ma20)}，但仍在 MA40 {_format_number(ma40)} 上方，进入回踩观察。"
    return f"现价 {_format_number(close)} 跌破 MA40 {_format_number(ma40)}，趋势纪律转弱。"


def _level_one_line(level: dict[str, Any]) -> str:
    value = _format_number(level.get("value"))
    source = level.get("source_label") or _level_source_label(str(level.get("source", "")))
    distance = level.get("distance_pct")
    if distance is None:
        return f"{level['display_label']} {value}（{source}）"
    direction = "上方" if distance > 0 else "下方"
    if abs(distance) < 0.005:
        return f"{level['display_label']} {value}（{source}，当前锚点）"
    return f"{level['display_label']} {value}（{source}，位于现价{direction} {abs(distance):.2f}%）"


def _support_pressure_text(item: dict[str, Any], *, include_trade_plan_levels: bool = True) -> str:
    ladder = _price_level_ladder(
        item,
        include_target=include_trade_plan_levels,
        include_stop=include_trade_plan_levels,
    )
    if not ladder:
        if include_trade_plan_levels:
            return "下一交易日价位：暂无足够 K 线数据计算支撑、压力和止损。"
        return "下一交易日价位：暂无足够 K 线数据计算支撑和压力。"
    price = _close_value(item)

    def nearest(kind: str, side: str = "") -> Optional[dict[str, Any]]:
        candidates = [level for level in ladder if level.get("kind") == kind]
        if not candidates:
            return None
        if price is None:
            return candidates[0]
        side_candidates = []
        for level in candidates:
            value = _as_float(level.get("value"))
            if value is None:
                continue
            if side == "above" and value >= price:
                side_candidates.append(level)
            elif side == "below" and value <= price:
                side_candidates.append(level)
        if side and not side_candidates:
            return None
        pool = side_candidates or candidates
        return min(pool, key=lambda level: abs(float(level["value"]) - price))

    candidates = [
        nearest("resistance", "above"),
        nearest("price"),
        nearest("support", "below"),
    ]
    if include_trade_plan_levels:
        candidates.append(nearest("stop", "below"))

    preferred = []
    for match in candidates:
        if match:
            preferred.append(_level_one_line(match))
    return "下一交易日价位：" + "；".join(preferred) + "。"


def _watchlist_web_action(item: dict[str, Any]) -> dict[str, str]:
    status = _trend_status_text(item)
    level_text = _support_pressure_text(item, include_trade_plan_levels=False)
    return {
        "stock": _stock_label(item),
        "bucket": "观察等待",
        "action": "技术跟踪",
        "trigger": "支撑/压力/均线",
        "position": "不在网页提前给买入计划",
        "text": f"{_stock_label(item)}：技术跟踪；趋势观察；{status}；{level_text}",
    }


def _join_steps(steps: list[str]) -> str:
    return "；".join(step.strip().rstrip("。；") for step in steps if step.strip())


def _position_playbook(item: dict[str, Any], action: dict[str, str]) -> str:
    ma20 = _indicator_value(item, "ma20")
    ma40 = _indicator_value(item, "ma40")
    support, pressure = _recent_support_pressure(item)
    stop = _hard_stop_value(item)
    steps = []
    if action.get("action") == "退出":
        steps.append("明日优先执行退出纪律，退出后不在 MA40 下方摊低成本。")
    elif action.get("action") == "减仓":
        steps.append("先按纪律降仓，1-2 日不能收回 MA20 就继续降低风险。")
    else:
        steps.append("只要未破 MA20/MA40，持仓以跟踪为主，不因为盘中波动提前改变计划。")
    if ma20 is not None:
        steps.append(f"若放量站稳 MA20 {_format_number(ma20)} 并保持板块共振，可保留仓位观察。")
    if pressure is not None:
        steps.append(f"若有效突破压力 {_format_number(pressure)} 后回踩不破，可把它视为强势延续确认，不追高加满。")
    if support is not None:
        steps.append(f"若跌破支撑 {_format_number(support)}，先把防守动作放在盈利想象之前。")
    if ma40 is not None:
        steps.append(f"若收盘跌破 MA40 {_format_number(ma40)}，按纪律退出。")
    if stop is not None:
        steps.append(f"硬止损参考 {_format_number(stop)}，这是成本线下方 15% 的生死线。")
    return "远期剧本：" + _join_steps(steps) + "。"


def _watch_playbook(item: dict[str, Any], action: dict[str, str], minimum_odds_ratio: float) -> str:
    support, pressure = _recent_support_pressure(item, include_trade_plan_levels=False)
    signal = str(item.get("signal") or "").strip()
    steps = []
    if pressure is not None:
        steps.append(f"若放量突破压力 {_format_number(pressure)} 后回踩确认，记录为强势复核点。")
    if support is not None:
        steps.append(f"若跌破支撑 {_format_number(support)}，标记为趋势转弱，等待结构重新稳定。")
    if signal:
        steps.append(f"技术标签以“{signal}”为准，未出现确认前只记录位置变化。")
    else:
        steps.append("技术触发位尚未明确，只跟踪支撑、压力、均线和量价变化。")
    return "远期剧本：" + _join_steps(steps) + "。"


def _chart_asset_dir(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}-assets")


def _chart_markdown_path(report_path: Path, chart_path: Path) -> str:
    try:
        return chart_path.relative_to(report_path.parent).as_posix()
    except ValueError:
        return os.path.relpath(chart_path, report_path.parent)


def _chart_meta(item: dict[str, Any], *, include_trade_plan_levels: bool = True) -> dict[str, Any]:
    candles = _ohlcv_rows(item)
    levels = _support_resistance_levels(
        item,
        include_target=include_trade_plan_levels,
        include_stop=include_trade_plan_levels,
    )
    price_ladder = _price_level_ladder(
        item,
        include_target=include_trade_plan_levels,
        include_stop=include_trade_plan_levels,
    )
    volumes = [candle["volume"] for candle in candles]
    return {
        "style": "candlestick" if len(candles) >= 2 else "none",
        "candle_count": len(candles),
        "has_volume": any(volume > 0 for volume in volumes),
        "has_ma5": len(candles) >= 5,
        "has_ma20": len(candles) >= 20,
        "has_ma40": len(candles) >= 40,
        "support": levels["support"],
        "resistance": levels["resistance"],
        "hard_stop": levels["hard_stop"],
        "price_ladder": price_ladder,
    }


def _level_note(level: dict[str, Any], label: str) -> str:
    value = _as_float(level.get("value"))
    if value is None:
        return f"{label}：暂无"
    if str(level.get("source") or "") == "hard_stop" or str(level.get("confidence") or "") == "hard":
        return f"{label}：{_format_number(value)}"
    confidence = str(level.get("confidence") or "low")
    confidence_text = {"high": "高", "medium": "中", "low": "低", "hard": "硬"}.get(confidence, confidence)
    source = _level_source_label(str(level.get("source") or ""))
    return f"{label}：{_format_number(value)}（{source}/{confidence_text}）"


def _layout_price_rail_labels(
    levels: list[dict[str, Any]],
    *,
    y_min: float,
    y_max: float,
    min_gap_ratio: float = 0.06,
) -> list[dict[str, Any]]:
    if not levels or y_max <= y_min:
        return []
    span = y_max - y_min
    min_gap = span * min_gap_ratio
    ordered = sorted(levels, key=lambda level: float(level["value"]), reverse=True)
    laid_out: list[dict[str, Any]] = []
    last_y: Optional[float] = None
    for level in ordered:
        label_y = float(level["value"])
        if last_y is not None and last_y - label_y < min_gap:
            label_y = last_y - min_gap
        label_y = max(y_min + span * 0.03, min(y_max - span * 0.03, label_y))
        row = dict(level)
        row["label_y"] = label_y
        laid_out.append(row)
        last_y = label_y
    for index in range(len(laid_out) - 2, -1, -1):
        if laid_out[index]["label_y"] - laid_out[index + 1]["label_y"] < min_gap:
            laid_out[index]["label_y"] = min(y_max - span * 0.03, laid_out[index + 1]["label_y"] + min_gap)
    return laid_out


def _wrap_chart_note_lines(lines: list[str], width: int = 22) -> str:
    wrapped_lines: list[str] = []
    for line in lines:
        chunks = textwrap.wrap(
            line,
            width=width,
            break_long_words=True,
            replace_whitespace=False,
            drop_whitespace=False,
        )
        wrapped_lines.extend(chunks or [""])
    return "\n".join(wrapped_lines)


def _set_chart_fonts(plt: Any) -> None:
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "Heiti TC", "SimHei", "DejaVu Sans"]


def _kline_chart_png_bytes(item: dict[str, Any], *, include_trade_plan_levels: bool = True) -> Optional[bytes]:
    candles = _ohlcv_rows(item)
    code = str(item.get("code") or "").strip()
    if len(candles) < 2 or not code:
        return None

    try:
        mpl_config_dir = Path(os.environ.get("MPLCONFIGDIR", "/private/tmp/lstock_matplotlib"))
        mpl_config_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("MPLCONFIGDIR", str(mpl_config_dir))
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
        from matplotlib.ticker import FuncFormatter
    except Exception:
        return None

    closes = [candle["close"] for candle in candles]
    volumes = [candle["volume"] for candle in candles]
    dates = [candle["date"] for candle in candles]
    x_values = list(range(len(candles)))
    levels = _support_resistance_levels(
        item,
        include_target=include_trade_plan_levels,
        include_stop=include_trade_plan_levels,
    )
    support = levels["support"]
    resistance = levels["resistance"]
    hard_stop = levels["hard_stop"]
    price_ladder = _price_level_ladder(
        item,
        include_target=include_trade_plan_levels,
        include_stop=include_trade_plan_levels,
    )
    ma5 = _rolling_average(closes, 5)
    ma20 = _rolling_average(closes, 20)
    ma40 = _rolling_average(closes, 40)

    _set_chart_fonts(plt)
    fig = plt.figure(figsize=(14.6, 8.2), dpi=130, facecolor="white")
    try:
        grid = fig.add_gridspec(2, 1, height_ratios=[4.2, 1.15], hspace=0.04)
        axis = fig.add_subplot(grid[0])
        volume_axis = fig.add_subplot(grid[1], sharex=axis)
        fig.subplots_adjust(left=0.06, right=0.82, top=0.91, bottom=0.09)

        up_color = "#d84a4a"
        down_color = "#1f9d66"
        neutral_color = "#7b8794"
        candle_width = 0.62
        price_span = max(closes) - min(closes) if closes else 1.0
        min_body = max(price_span * 0.003, 0.01)

        for index, candle in enumerate(candles):
            is_up = candle["close"] >= candle["open"]
            color = up_color if is_up else down_color
            axis.vlines(index, candle["low"], candle["high"], color=color, linewidth=1.15, alpha=0.95)
            body_bottom = min(candle["open"], candle["close"])
            body_height = max(abs(candle["close"] - candle["open"]), min_body)
            axis.add_patch(
                Rectangle(
                    (index - candle_width / 2, body_bottom),
                    candle_width,
                    body_height,
                    facecolor=color,
                    edgecolor=color,
                    linewidth=0.8,
                    alpha=0.92,
                )
            )
            volume_axis.bar(index, candle["volume"], color=color, width=candle_width, alpha=0.45, linewidth=0)

        if len(closes) >= 5:
            axis.plot(x_values, ma5, color="#f5a623", linewidth=1.35, label="MA5")
        if len(closes) >= 20:
            axis.plot(x_values, ma20, color="#3366cc", linewidth=1.45, label="MA20")
        if len(closes) >= 40:
            axis.plot(x_values, ma40, color="#8f5cc2", linewidth=1.45, label="MA40")

        level_colors = {
            "resistance": "#b91c1c",
            "price": "#2563eb",
            "support": "#15803d",
            "stop": "#7f1d1d",
        }

        def draw_static_zone(level: dict[str, Any]) -> None:
            if level.get("is_dynamic"):
                return
            value = _as_float(level.get("value"))
            low = _as_float(level.get("band_low"))
            high = _as_float(level.get("band_high"))
            if value is None or low is None or high is None:
                return
            color = level_colors.get(str(level.get("kind") or ""), neutral_color)
            axis.axhspan(low, high, color=color, alpha=0.08, linewidth=0)
            axis.axhline(value, color=color, linestyle="--", linewidth=1.0, alpha=0.55)

        for level in price_ladder:
            if level.get("kind") in {"support", "resistance"}:
                draw_static_zone(level)

        latest = candles[-1]
        title = (
            f"{item.get('name') or code} {code} 日K  "
            f"{latest['date']} 收盘 {_format_number(latest['close'])}"
        )
        axis.set_title(title, loc="left", fontsize=15, fontweight="bold", color="#1f2933", pad=14)
        axis.grid(True, color="#e8edf3", linewidth=0.8)
        axis.set_facecolor("#ffffff")
        axis.tick_params(axis="x", labelbottom=False)
        axis.tick_params(axis="y", labelsize=9, colors="#52606f")
        axis.set_xlim(-1, len(candles) + 1.5)
        y_values = [candle["low"] for candle in candles] + [candle["high"] for candle in candles]
        for level in (support, resistance, hard_stop):
            value = _as_float(level.get("value"))
            if value is not None:
                y_values.append(value)
        for level in price_ladder:
            value = _as_float(level.get("value"))
            if value is not None:
                y_values.append(value)
            band_low = _as_float(level.get("band_low"))
            band_high = _as_float(level.get("band_high"))
            if band_low is not None:
                y_values.append(band_low)
            if band_high is not None:
                y_values.append(band_high)
        y_min, y_max = min(y_values), max(y_values)
        padding = max((y_max - y_min) * 0.08, abs(latest["close"]) * 0.015, 0.1)
        axis.set_ylim(y_min - padding, y_max + padding)

        rail_levels = _layout_price_rail_labels(
            [
                level
                for level in price_ladder
                if level.get("kind") in {"resistance", "price", "support", "stop"}
                and _as_float(level.get("value")) is not None
            ],
            y_min=y_min - padding,
            y_max=y_max + padding,
            min_gap_ratio=0.055,
        )
        for level in rail_levels:
            value = float(level["value"])
            label_y = float(level["label_y"])
            color = level_colors.get(str(level.get("kind") or ""), neutral_color)
            label = f"{level['display_label']} {value:.2f}"
            source = str(level.get("source_label") or "")
            text = f"{label} · {source}" if source else label
            axis.annotate(
                text,
                xy=(len(candles) - 0.35, value),
                xycoords="data",
                xytext=(1.015, label_y),
                textcoords=axis.get_yaxis_transform(),
                ha="left",
                va="center",
                fontsize=8.8,
                color=color,
                clip_on=False,
                arrowprops={
                    "arrowstyle": "-",
                    "color": color,
                    "linewidth": 0.9,
                    "alpha": 0.75,
                    "shrinkA": 0,
                    "shrinkB": 4,
                },
            )
        axis.legend(loc="upper left", fontsize=8, frameon=False, ncol=3)

        volume_axis.grid(True, axis="y", color="#edf1f5", linewidth=0.8)
        volume_axis.set_facecolor("#ffffff")
        volume_axis.tick_params(axis="y", labelsize=8, colors="#7b8794")
        volume_axis.set_ylabel("成交量", fontsize=8, color="#7b8794")
        volume_axis.yaxis.set_major_formatter(
            FuncFormatter(lambda value, _pos: f"{value / 100000000:.1f}亿" if value >= 100000000 else f"{value / 10000:.0f}万")
        )
        volume_axis.yaxis.offsetText.set_visible(False)
        if dates:
            ticks = sorted(set([0, len(dates) // 4, len(dates) // 2, len(dates) * 3 // 4, len(dates) - 1]))
            volume_axis.set_xticks(ticks)
            volume_axis.set_xticklabels([dates[index] for index in ticks], rotation=0, fontsize=8, color="#52606f")

        buffer = BytesIO()
        fig.savefig(buffer, format="png", facecolor="white")
        return buffer.getvalue()
    finally:
        plt.close(fig)


def _safe_chart_code(value: Any) -> str:
    safe = "".join(
        char
        for char in str(value or "").strip()
        if char.isascii() and (char.isalnum() or char in {"_", "-"})
    )
    return safe or "chart"


def _write_kline_chart(
    item: dict[str, Any],
    report_path: Path,
    *,
    identity: str = "",
    include_trade_plan_levels: bool = True,
) -> Optional[Path]:
    code = _code_key(item.get("code"))
    png_bytes = _kline_chart_png_bytes(item, include_trade_plan_levels=include_trade_plan_levels)
    if png_bytes is None or not code:
        return None

    asset_dir = _chart_asset_dir(report_path)
    asset_dir.mkdir(parents=True, exist_ok=True)
    chart_path = asset_dir / f"{_safe_chart_code(code)}.png"
    if chart_path.exists() and identity:
        chart_path = asset_dir / f"{_safe_chart_code(identity)}-{_safe_chart_code(code)}.png"
    chart_path.write_bytes(png_bytes)
    return chart_path


def _kline_chart_data_uri(item: dict[str, Any], *, include_trade_plan_levels: bool = True) -> Optional[str]:
    png_bytes = _kline_chart_png_bytes(item, include_trade_plan_levels=include_trade_plan_levels)
    if png_bytes is None:
        return None
    encoded = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _prepare_chart_paths(
    items: list[dict[str, Any]],
    output_path: Optional[Path],
    *,
    identity: str,
    include_trade_plan_levels: bool = True,
) -> dict[tuple[str, str], str]:
    if output_path is None:
        return {}
    paths: dict[tuple[str, str], str] = {}
    for item in items:
        code = _code_key(item.get("code"))
        map_key = (identity, code)
        if not code or map_key in paths:
            continue
        chart_path = _write_kline_chart(
            item,
            output_path,
            identity=identity,
            include_trade_plan_levels=include_trade_plan_levels,
        )
        if chart_path is not None:
            paths[map_key] = _chart_markdown_path(output_path, chart_path)
    return paths


def _append_security_section(
    lines: list[str],
    item: dict[str, Any],
    action: dict[str, str],
    chart_paths: dict[tuple[str, str], str],
    identity: str,
    minimum_odds_ratio: float,
) -> None:
    code = _code_key(item.get("code"))
    label = _stock_label(item)
    lines.extend([f"### {_md_text(label)}", ""])
    chart_path = chart_paths.get((identity, code))
    trend_text = _trend_status_text(item)
    support_text = _support_pressure_text(item, include_trade_plan_levels=identity == "position")
    action_text = _md_text(action.get("text", "观察等待。"))
    playbook_text = _position_playbook(item, action) if identity == "position" else _watch_playbook(item, action, minimum_odds_ratio)
    if chart_path:
        alt_name = item.get("name") or code
        lines.append(f"![{_md_text(alt_name)} K线图]({_html(chart_path)})")
        lines.append("")
        lines.append(f"- K 线现状：{trend_text}")
        lines.append(f"- 支撑/压力：{support_text}")
        lines.append(f"- 当下动作：{action_text}")
        lines.append(f"- {playbook_text}")
    else:
        lines.append(f"- K 线现状：{trend_text}")
        lines.append(f"- 支撑/压力：{support_text}")
        lines.append(f"- 当下动作：{action_text}")
        lines.append(f"- {playbook_text}")
    lines.append("")


def _analysis_items(snapshot: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    stock_data = _stock_data_by_code(snapshot)
    positions = _merge_stock_data(_snapshot_items(snapshot, "positions"), stock_data)
    position_codes = {_code_key(item.get("code")) for item in positions if isinstance(item, dict) and _code_key(item.get("code"))}
    watchlist = _merge_stock_data(
        [item for item in _snapshot_items(snapshot, "watchlist") if _code_key(item.get("code")) not in position_codes],
        stock_data,
    )
    return positions, watchlist


def _append_stock_playbooks(
    lines: list[str],
    snapshot: dict[str, Any],
    position_actions: list[dict[str, str]],
    watch_actions: list[dict[str, str]],
    chart_paths: dict[tuple[str, str], str],
) -> None:
    positions, watchlist = _analysis_items(snapshot)
    minimum_odds = _minimum_odds_ratio(snapshot)
    market = snapshot.get("market") if isinstance(snapshot.get("market"), dict) else {}
    emotion = snapshot.get("emotion") if isinstance(snapshot.get("emotion"), dict) else {}

    lines.extend(["## 持仓诊断", ""])
    if not positions:
        lines.extend(["- 当前没有持仓。", ""])
    for index, item in enumerate(positions):
        action = position_actions[index] if index < len(position_actions) else position_action(item)
        _append_security_section(lines, item, action, chart_paths, "position", minimum_odds)

    lines.extend(["## 关注池剧本", ""])
    if not watchlist:
        lines.extend(["- 当前没有非持仓关注股。", ""])
    for index, item in enumerate(watchlist):
        action = watch_actions[index] if index < len(watch_actions) else watch_action(item, minimum_odds, market, emotion)
        _append_security_section(lines, item, action, chart_paths, "watch", minimum_odds)


def _html_list(items: list[str], class_name: str = "action-list") -> str:
    if not items:
        items = ["无"]
    body = "".join(f"<li>{_html(item)}</li>" for item in items)
    return f'<ul class="{_html(class_name)}">{body}</ul>'


def _section(section_id: str, title: str, body: str) -> str:
    return (
        f'<section class="report-section" id="{_html(section_id)}">'
        f'<h2 class="section-title">{_html(title)}</h2>'
        f"{body}"
        "</section>"
    )


def _section_heading_html(title: str, eyebrow: str = "", right_html: str = "") -> str:
    eyebrow_html = f'<p class="eyebrow">{_html(eyebrow)}</p>' if eyebrow else ""
    return (
        '<div class="section-heading">'
        f"<div>{eyebrow_html}<h2>{_html(title)}</h2></div>"
        f"{right_html}"
        "</div>"
    )


def _market_metric_html(label: str, value: str, note: str) -> str:
    return (
        '<div class="kpi-card metric-card">'
        f'<div class="kpi-label">{_html(label)}</div>'
        f'<div class="kpi-value">{_html(value)}</div>'
        f'<div class="kpi-note">{_html(note)}</div>'
        "</div>"
    )


def _today_script_html(snapshot: dict[str, Any]) -> str:
    market = snapshot.get("market") if isinstance(snapshot.get("market"), dict) else {}
    summary = market.get("summary") if isinstance(market.get("summary"), dict) else {}
    stance = str(market.get("stance") or summary.get("stance") or "观察")
    thesis = str(
        summary.get("thesis")
        or "指数结构仍有承接，但短线情绪偏热，今天以纪律持仓和技术跟踪为主。"
    )
    risk = str(
        summary.get("risk")
        or "未出现清晰回踩或有效突破前，关注池只记录技术位置，不当作交易清单。"
    )
    right_html = f'<span class="status-pill">{_html(stance)}</span>'
    body = (
        _section_heading_html("今日剧本", "今日怎么做", right_html)
        + '<div class="script-hero">'
        + f'<div class="script-badge">{_html(stance)}</div>'
        + "<div>"
        + f"<h3>{_html(thesis)}</h3>"
        + f"<p>{_html(risk)}</p>"
        + '<div class="script-grid">'
        + "<div><strong>持仓</strong><span>按 MA20/MA40 与硬止损纪律处理，不因盘中波动提前改计划。</span></div>"
        + "<div><strong>关注池</strong><span>只看接近支撑、突破压力、趋势转弱三类技术位置。</span></div>"
        + "<div><strong>风险边界</strong><span>市场偏热时不追高，先等回踩确认或有效突破。</span></div>"
        + "</div></div></div>"
    )
    return f'<section class="report-section today-script" id="today-script">{body}</section>'


def _emotion_temperature_value(emotion: dict[str, Any]) -> str:
    stage = _emotion_stage(emotion)
    height = _format_number(emotion.get("height"), 0)
    if height != "未知":
        return f"{stage} {height}"
    return stage


def _limit_break_value(emotion: dict[str, Any]) -> str:
    return f"{_format_number(emotion.get('limit_up_count'), 0)} / {_format_pct(emotion.get('break_board_rate'))}"


def _market_thermometer_html(snapshot: dict[str, Any]) -> str:
    market = snapshot.get("market") if isinstance(snapshot.get("market"), dict) else {}
    emotion = snapshot.get("emotion") if isinstance(snapshot.get("emotion"), dict) else {}
    body = (
        _section_heading_html("市场温度计", "为什么这么做")
        + '<div class="kpi-grid market-grid">'
        + _market_metric_html(
            "指数结构",
            _market_index_summary(market),
            "核心指数站上关键均线越多，代表市场结构越有承接。",
        )
        + _market_metric_html(
            "情绪温度",
            _emotion_temperature_value(emotion),
            "连板高度越高，短线情绪越热；热不等于适合追高。",
        )
        + _market_metric_html(
            "涨停 / 炸板",
            _limit_break_value(emotion),
            "涨停数量看赚钱效应，炸板率看追高失败成本。",
        )
        + _market_metric_html(
            "主线资金",
            _sector_summary(snapshot),
            _sector_line(snapshot),
        )
        + "</div>"
    )
    return f'<section class="report-section market-thermometer" id="market-thermometer">{body}</section>'


def _action_chip_class(action_name: str) -> str:
    if action_name in {"退出", "减仓"}:
        return "chip chip-risk"
    if action_name == "技术跟踪":
        return "chip chip-watch"
    if action_name == "持有":
        return "chip chip-position"
    return "chip chip-action"


def _action_matrix_row_html(action: dict[str, str], identity: str, item: Optional[dict[str, Any]] = None) -> str:
    action_name = action.get("action", "观察")
    stock = action.get("stock", "未知")
    identity_class = "chip-position" if identity == "持仓" else "chip-watch"
    technical_status = _trend_status_text(item) if isinstance(item, dict) else ACTION_DISPLAY_NAMES.get(
        action.get("bucket", ""), action.get("bucket", "观察等待")
    )
    trigger = action.get("trigger")
    if not trigger:
        trigger = "跌破 MA20 减仓；跌破 MA40 退出" if identity == "持仓" else "支撑/压力/均线"
    return (
        "<tr>"
        f"<td>{_html(stock)}</td>"
        f'<td><span class="chip {identity_class}">{_html(identity)}</span></td>'
        f'<td><span class="{_action_chip_class(action_name)}">{_html(action_name)}</span></td>'
        f"<td>{_html(technical_status)}</td>"
        f"<td>{_html(trigger)}</td>"
        f"<td>{_html(action.get('text', '观察等待。'))}</td>"
        "</tr>"
    )


def _action_matrix_html(
    position_actions: list[dict[str, str]],
    positions: list[dict[str, Any]],
    watch_items: list[dict[str, Any]],
) -> str:
    rows: list[str] = []
    for index, action in enumerate(position_actions):
        item = positions[index] if index < len(positions) else None
        rows.append(_action_matrix_row_html(action, "持仓", item))
    for item in watch_items:
        rows.append(_action_matrix_row_html(_watchlist_web_action(item), "关注池", item))
    if not rows:
        rows.append('<tr><td colspan="6" class="empty-cell">暂无需要展示的股票动作。</td></tr>')
    body = (
        _section_heading_html("行动矩阵", "今天盯什么")
        + '<div class="matrix-wrap">'
        + "<table>"
        + "<thead><tr><th>股票</th><th>身份</th><th>动作</th><th>技术状态</th><th>触发 / 失效</th><th>今天怎么做</th></tr></thead>"
        + f"<tbody>{''.join(rows)}</tbody>"
        + "</table></div>"
    )
    return f'<section class="report-section action-matrix" id="action-matrix">{body}</section>'


def _preferred_price_levels(item: dict[str, Any], *, include_trade_plan_levels: bool = True) -> list[dict[str, Any]]:
    ladder = _price_level_ladder(
        item,
        include_target=include_trade_plan_levels,
        include_stop=include_trade_plan_levels,
    )
    price = _close_value(item)

    def nearest(kind: str, side: str = "") -> Optional[dict[str, Any]]:
        candidates = [level for level in ladder if level.get("kind") == kind]
        if not candidates:
            return None
        if price is None:
            return candidates[0]
        side_candidates = []
        for level in candidates:
            value = _as_float(level.get("value"))
            if value is None:
                continue
            if side == "above" and value >= price:
                side_candidates.append(level)
            elif side == "below" and value <= price:
                side_candidates.append(level)
        if side and not side_candidates:
            return None
        pool = side_candidates or candidates
        return min(pool, key=lambda level: abs(float(level["value"]) - price))

    levels = [
        nearest("resistance", "above"),
        nearest("price"),
        nearest("support", "below"),
    ]
    if include_trade_plan_levels:
        levels.append(nearest("stop", "below"))
    return [level for level in levels if level]


def _price_level_meaning(level: dict[str, Any]) -> str:
    label = str(level.get("display_label") or "")
    if label == "上方压力":
        return "突破后看回踩"
    if label == "当前价":
        return "当前位置"
    if label == "下方支撑":
        return "回踩观察"
    if label == "硬止损":
        return "不是技术支撑"
    return "观察"


def _price_level_table_html(item: dict[str, Any], *, include_trade_plan_levels: bool = True) -> str:
    rows = []
    for level in _preferred_price_levels(item, include_trade_plan_levels=include_trade_plan_levels):
        rows.append(
            '<div class="level-table-row">'
            f"<span>{_html(level.get('display_label', '价位'))}</span>"
            f"<strong>{_html(_format_number(level.get('value')))}</strong>"
            f"<em>{_html(level.get('source_label') or _level_source_label(str(level.get('source', ''))))}</em>"
            f"<em>{_html(_price_level_meaning(level))}</em>"
            "</div>"
        )
    if not rows:
        rows.append('<div class="level-table-row"><span>价位</span><strong>未知</strong><em>数据不足</em><em>观察</em></div>')
    return '<div class="level-table">' + "".join(rows) + "</div>"


def _collapsible_section_html(
    *,
    section_id: str,
    title: str,
    eyebrow: str,
    body_html: str,
    open_by_default: bool = False,
    extra_class: str = "",
) -> str:
    open_attr = " open" if open_by_default else ""
    extra = f" {extra_class}" if extra_class else ""
    return (
        f'<details class="report-section collapsible{extra}" id="{_html(section_id)}"{open_attr}>'
        "<summary>"
        f"<span><small>{_html(eyebrow)}</small><strong>{_html(title)}</strong></span>"
        '<span class="summary-caret">展开/收起</span>'
        "</summary>"
        f'<div class="collapsible-body">{body_html}</div>'
        "</details>"
    )


def _fallback_source(item: dict[str, Any]) -> Optional[str]:
    fallback = item.get("fallback_from")
    if isinstance(fallback, dict) and fallback.get("source"):
        return str(fallback.get("source"))
    if isinstance(fallback, str) and fallback:
        return fallback
    return None


def _price_ladder_summary(item: dict[str, Any], *, include_trade_plan_levels: bool = True) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for level in _preferred_price_levels(item, include_trade_plan_levels=include_trade_plan_levels):
        summary.append(
            {
                "display_label": level.get("display_label"),
                "value": level.get("value"),
                "source": level.get("source"),
                "source_label": level.get("source_label"),
                "kind": level.get("kind"),
                "is_dynamic": level.get("is_dynamic"),
            }
        )
    return summary


def _chart_input_summary(item: dict[str, Any], identity: str) -> dict[str, Any]:
    include_trade_plan_levels = identity == "position"
    meta = _chart_meta(item, include_trade_plan_levels=include_trade_plan_levels)
    return {
        "identity": identity,
        "code": item.get("code"),
        "name": item.get("name"),
        "source": item.get("source"),
        "fallback_source": _fallback_source(item),
        "candle_count": meta.get("candle_count"),
        "has_volume": meta.get("has_volume"),
        "has_ma5": meta.get("has_ma5"),
        "has_ma20": meta.get("has_ma20"),
        "has_ma40": meta.get("has_ma40"),
        "price_ladder": _price_ladder_summary(item, include_trade_plan_levels=include_trade_plan_levels),
    }


def _chart_input_summaries(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    positions, watchlist = _analysis_items(snapshot)
    summaries = [_chart_input_summary(item, "position") for item in positions]
    summaries.extend(_chart_input_summary(item, "watchlist") for item in watchlist)
    return summaries


def _data_appendix_html(snapshot: dict[str, Any]) -> str:
    market = snapshot.get("market") if isinstance(snapshot.get("market"), dict) else {}
    emotion = snapshot.get("emotion") if isinstance(snapshot.get("emotion"), dict) else {}
    funds = snapshot.get("funds") if isinstance(snapshot.get("funds"), dict) else {}
    sectors = snapshot.get("sectors") if isinstance(snapshot.get("sectors"), dict) else {}
    stocks = snapshot.get("stocks") if isinstance(snapshot.get("stocks"), dict) else {}
    evidence = {
        "gate": snapshot.get("gate", {}),
        "market": _compact_group(market),
        "emotion": _compact_group(emotion),
        "funds": _compact_group(funds),
        "sectors": _compact_group(sectors),
        "stocks": _compact_group(stocks),
        "chart_inputs": _chart_input_summaries(snapshot),
    }
    body = (
        '<div class="appendix-note">数据闸门、原始摘要、fallback 与图表输入保留在这里，日常阅读可以保持收起。</div>'
        f'<pre class="data-block">{html.escape(_json(evidence), quote=False)}</pre>'
    )
    return _collapsible_section_html(
        section_id="data-appendix",
        title="数据附录",
        eyebrow="原始证据 · 默认收起",
        body_html=body,
        open_by_default=False,
        extra_class="data-appendix",
    )


def _action_groups_html(position_actions: list[dict[str, str]], watch_actions: list[dict[str, str]]) -> str:
    cards = []
    all_actions = position_actions + watch_actions
    for bucket in ACTION_BUCKETS:
        texts = [action.get("text", "") for action in all_actions if action.get("bucket") == bucket]
        cards.append(
            '<div class="action-group">'
            f"<h3>{_html(ACTION_DISPLAY_NAMES.get(bucket, bucket))}</h3>"
            f"{_html_list(texts)}"
            "</div>"
        )
    return '<div class="action-groups">' + "".join(cards) + "</div>"


def _kpi_cards_html(snapshot: dict[str, Any]) -> str:
    market = snapshot.get("market") if isinstance(snapshot.get("market"), dict) else {}
    emotion = snapshot.get("emotion") if isinstance(snapshot.get("emotion"), dict) else {}
    position_actions, watch_actions = _collect_actions(snapshot)
    kpis = [
        ("市场结构", _market_index_summary(market), _market_environment(market)),
        ("情绪温度", _emotion_summary(emotion), _emotion_stage(emotion)),
        ("主线板块", _sector_summary(snapshot), _sector_line(snapshot)),
        ("执行队列", f"{len(position_actions)} 持仓 / {len(watch_actions)} 关注", _reserve_cash_line(snapshot)),
    ]
    cards = []
    for label, value, note in kpis:
        cards.append(
            '<div class="kpi-card">'
            f'<div class="kpi-label">{_html(label)}</div>'
            f'<div class="kpi-value">{_html(value)}</div>'
            f'<div class="kpi-note">{_html(note)}</div>'
            "</div>"
        )
    return '<div class="kpi-grid">' + "".join(cards) + "</div>"


def _condition_items_html(item: dict[str, Any], action: dict[str, str], identity: str) -> str:
    items = [
        ("趋势", _trend_status_text(item)),
        ("触发", action.get("trigger") or ("MA20/MA40" if identity == "position" else "支撑/压力/均线")),
        ("价位", _support_pressure_text(item, include_trade_plan_levels=identity == "position")),
    ]
    if identity == "position":
        items.append(("仓位", action.get("position") or "按纪律处理，不加破位仓"))
    else:
        items.append(("范围", "关注池只记录技术位置，不在网页生成交易预案。"))

    rows = [
        f"<li><strong>{_html(label)}</strong><span>{_html(str(value or '观察'))}</span></li>"
        for label, value in items
    ]
    return '<ul class="condition-list">' + "".join(rows) + "</ul>"


def _playbook_details_html(playbook_text: str) -> str:
    body = str(playbook_text or "暂无远期剧本。").strip()
    if body.startswith("远期剧本："):
        body = body.removeprefix("远期剧本：").strip()
    return (
        '<details class="playbook-details">'
        "<summary>"
        "<span>远期剧本</span>"
        '<span class="summary-caret">展开/收起</span>'
        "</summary>"
        f'<div class="playbook-body">{_html(body)}</div>'
        "</details>"
    )


def _stock_card_html(
    item: dict[str, Any],
    action: dict[str, str],
    identity: str,
    minimum_odds_ratio: float,
    chart_data_uri: Optional[str] = None,
) -> str:
    code = str(item.get("code") or "").strip()
    label = _stock_label(item)
    identity_label = "持仓" if identity == "position" else "关注"
    trend_text = _trend_status_text(item)
    level_table = _price_level_table_html(item, include_trade_plan_levels=identity == "position")
    action_text = action.get("text", "观察等待。")
    playbook_text = (
        _position_playbook(item, action)
        if identity == "position"
        else "技术跟踪：只记录支撑、压力、均线与趋势变化；有效突破、回踩确认或趋势转弱时，再单独复核；当前不生成交易预案。"
    )
    chart_html = (
        '<button class="chart-image-button" type="button" onclick="openChartLightbox(this)" '
        f'aria-label="放大查看 {_html(label)} K线图">'
        f'<img src="{_html(chart_data_uri)}" alt="{_html(label)} K线图">'
        "</button>"
        f'<button class="chart-zoom-button" type="button" onclick="openChartLightbox(this)" aria-label="放大查看 {_html(label)} K线图">放大查看</button>'
        if chart_data_uri
        else '<div class="chart-empty">K 线数据不足，图表暂不可用</div>'
    )
    identity_chip = "chip-position" if identity == "position" else "chip-watch"
    return (
        '<article class="stock-card">'
        '<div class="stock-card-header">'
        "<div>"
        f'<p class="eyebrow">{_html(identity_label)} · {_html(code or "未知代码")}</p>'
        f"<h3>{_html(label)}</h3>"
        "</div>"
        '<div class="stock-card-tags">'
        f'<span class="chip {identity_chip}">{_html(identity_label)}</span>'
        f'<span class="{_action_chip_class(action.get("action", "观察"))}">{_html(action.get("action", "观察"))}</span>'
        "</div>"
        "</div>"
        '<div class="stock-card-layout">'
        '<div class="chart-panel">'
        '<div class="chart-frame">'
        f"{chart_html}"
        "</div>"
        '<p class="chart-note">图中右侧价位轨道使用中文标签；图表解读已移到右侧信息区，动态均线不画成历史水平支撑线。</p>'
        "</div>"
        '<aside class="stock-insight-panel">'
        f'<div class="compact-detail compact-primary"><div class="detail-label">核心判断</div><div class="detail-value">{_html(trend_text)}</div></div>'
        f'<div class="compact-detail"><div class="detail-label">动作条件</div>{_condition_items_html(item, action, identity)}</div>'
        f'<div class="compact-detail"><div class="detail-label">价位表</div>{level_table}</div>'
        f'<div class="compact-detail"><div class="detail-label">当下动作</div><div class="detail-value">{_html(action_text)}</div></div>'
        f"{_playbook_details_html(playbook_text)}"
        "</aside>"
        "</div>"
        "</article>"
    )


def _action_table_html(position_actions: list[dict[str, str]], watch_actions: list[dict[str, str]]) -> str:
    rows = []
    for action in position_actions:
        rows.append(
            "<tr>"
            f"<td>{_html(action.get('stock', '未知'))}</td>"
            "<td>持仓</td>"
            f"<td>{_html(ACTION_DISPLAY_NAMES.get(action.get('bucket', ''), action.get('bucket', '观察等待')))}</td>"
            f"<td>{_html(action.get('action', '观察'))}</td>"
            "<td>MA20/MA40</td>"
            "<td>按纪律处理，不加破位仓</td>"
            f"<td>{_html(action.get('text', ''))}</td>"
            "</tr>"
        )
    for action in watch_actions:
        rows.append(
            "<tr>"
            f"<td>{_html(action.get('stock', '未知'))}</td>"
            "<td>关注</td>"
            f"<td>{_html(ACTION_DISPLAY_NAMES.get(action.get('bucket', ''), action.get('bucket', '观察等待')))}</td>"
            f"<td>{_html(action.get('action', '观察'))}</td>"
            f"<td>{_html(action.get('trigger') or '支撑/压力/均线')}</td>"
            f"<td>{_html(action.get('position') or _watch_position_size(action))}</td>"
            f"<td>{_html(action.get('text', ''))}</td>"
            "</tr>"
        )
    if not rows:
        rows.append("<tr><td>无</td><td>-</td><td>观察等待</td><td>无</td><td>-</td><td>保留现金</td><td>今日无个股动作</td></tr>")
    return (
        '<table class="action-table">'
        "<thead><tr><th>股票</th><th>身份</th><th>结论</th><th>动作</th><th>触发位</th><th>仓位</th><th>理由</th></tr></thead>"
        "<tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def render_data_block_html(snapshot: dict[str, Any]) -> str:
    gate = snapshot.get("gate") if isinstance(snapshot.get("gate"), dict) else {}
    blocks = []
    for block in _as_list(gate.get("blocks")):
        if isinstance(block, dict):
            group = block.get("group", "未知")
            reason = block.get("reason", "blocked")
            missing = "、".join(str(item) for item in _as_list(block.get("missing"))) or "未列明"
            blocks.append(f"{group}：{reason}；缺失：{missing}")
        else:
            blocks.append(str(block))

    task_cards: list[str] = []
    for index, task in enumerate(_chrome_tasks(snapshot), start=1):
        group = task.get("group", "unknown")
        name = task.get("name", "补数任务")
        details: list[tuple[str, str]] = []
        for key in ("url", "override_path", "override_key", "expected_status", "success_criteria"):
            if task.get(key):
                details.append((key, str(task[key])))
        required_fields = task.get("required_fields")
        if isinstance(required_fields, list):
            details.append(("required_fields", ", ".join(str(field) for field in required_fields)))

        detail_html = "".join(
            f"<dt>{_html(label)}</dt><dd>{_html(value)}</dd>"
            for label, value in details
        )
        example_html = ""
        if "example_override" in task:
            example_html = (
                "<h4>example_override</h4>"
                f'<pre class="data-block">{_html(_json(task["example_override"]))}</pre>'
            )
        task_cards.append(
            '<div class="evidence-item">'
            f"<h3>{_html(index)}. {_html(group)}：{_html(name)}</h3>"
            f"<dl>{detail_html}</dl>"
            f"{example_html}"
            "</div>"
        )
    if task_cards:
        chrome_tasks_html = '<div class="evidence-grid">' + "".join(task_cards) + "</div>"
    else:
        chrome_tasks_html = "<p>未提供 chrome_tasks；先补齐 gate.blocks 中的缺失数据。</p>"

    body = (
        "<p>数据不足，禁止生成正式买卖建议。先完成补数或确认数据覆盖，再重新渲染正式交易报告。</p>"
        "<p>补数报告只说明缺什么、去哪里补、覆盖文件怎么写；它不是交易报告，不生成正式买卖建议。</p>"
        f"{_html_list(blocks, 'action-list')}"
        "<h3>Chrome 补数任务</h3>"
        f"{chrome_tasks_html}"
        "<h3>原始证据</h3>"
        f'<pre class="data-block">{_html(_json(snapshot.get("gate", {})))}</pre>'
    )
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return _html_document(now, "l-stock 补数报告", _section("data", "数据闸门", body), _gate_status(snapshot), include_nav=False)


def _html_document(now: str, title: str, main_html: str, gate_status: str, include_nav: bool = True) -> str:
    nav_html = ""
    lightbox_html = ""
    export_button_html = ""
    shell_class = "app-shell"
    if include_nav:
        export_button_html = '<button class="export-button" type="button" onclick="exportPdf()">导出 PDF</button>'
        nav_items = [
            ("today-script", "今日剧本"),
            ("market-thermometer", "市场温度计"),
            ("action-matrix", "行动矩阵"),
            ("positions", "持仓诊断"),
            ("watchlist-tracking", "关注池技术跟踪"),
            ("data-appendix", "数据附录"),
        ]
        links = "".join(f'<a class="nav-link" href="#{_html(item_id)}">{_html(label)}</a>' for item_id, label in nav_items)
        nav_html = f'<nav class="side-nav"><div class="brand">l-stock</div>{links}</nav>'
        lightbox_html = (
            '<div class="chart-lightbox" id="chart-lightbox" aria-hidden="true" onclick="if (event.target === this) closeChartLightbox()">'
            '<button class="chart-lightbox-close" type="button" onclick="closeChartLightbox()" aria-label="关闭放大图">关闭</button>'
            '<img id="chart-lightbox-image" alt="放大的 K 线图">'
            "</div>"
        )
    else:
        shell_class = "app-shell app-shell-single"
    return (
        "<!doctype html>\n"
        '<html lang="zh-CN">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_html(title)}</title>\n"
        f"<style>{HTML_REPORT_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        f'<div class="{shell_class}">'
        f"{nav_html}"
        '<main class="report-main">'
        '<header class="top-bar">'
        "<div>"
        f'<h1 class="report-title">{_html(title)}</h1>'
        f'<div class="report-meta">报告时间：{_html(now)}</div>'
        "</div>"
        '<div class="header-tools">'
        f'<span class="gate-pill" data-status="{_html(gate_status)}">Gate {_html(gate_status)}</span>'
        f"{export_button_html}"
        "</div>"
        "</header>"
        f'<div class="content">{main_html}</div>'
        "</main>"
        "</div>"
        f"{lightbox_html}"
        f"<script>{HTML_REPORT_JS}</script>\n"
        "</body>\n"
        "</html>\n"
    )


def _chart_data_uris(
    items: list[dict[str, Any]],
    *,
    identity: str,
    include_trade_plan_levels: bool = True,
) -> dict[tuple[str, str], str]:
    uris: dict[tuple[str, str], str] = {}
    for item in items:
        code = _code_key(item.get("code"))
        map_key = (identity, code)
        if not code or map_key in uris:
            continue
        data_uri = _kline_chart_data_uri(item, include_trade_plan_levels=include_trade_plan_levels)
        if data_uri is not None:
            uris[map_key] = data_uri
    return uris


def _render_html_report(snapshot: dict[str, Any]) -> tuple[str, int]:
    if _gate_status(snapshot) not in {"PASS", "WARN"}:
        return render_data_block_html(snapshot), 0

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    position_actions, _watch_actions = _collect_actions(snapshot)
    positions, watchlist = _analysis_items(snapshot)
    minimum_odds = _minimum_odds_ratio(snapshot)
    chart_data_uris = _chart_data_uris(positions, identity="position", include_trade_plan_levels=True)
    chart_data_uris.update(_chart_data_uris(watchlist, identity="watch", include_trade_plan_levels=False))
    watch_web_actions = [_watchlist_web_action(item) for item in watchlist]

    position_cards = []
    for index, item in enumerate(positions):
        action = position_actions[index] if index < len(position_actions) else position_action(item)
        code = _code_key(item.get("code"))
        position_cards.append(_stock_card_html(item, action, "position", minimum_odds, chart_data_uris.get(("position", code))))
    watch_cards = []
    for index, item in enumerate(watchlist):
        action = watch_web_actions[index] if index < len(watch_web_actions) else _watchlist_web_action(item)
        code = _code_key(item.get("code"))
        watch_cards.append(_stock_card_html(item, action, "watch", minimum_odds, chart_data_uris.get(("watch", code))))

    position_body = '<div class="stock-grid">' + "".join(position_cards or ["<p>当前没有持仓。</p>"]) + "</div>"
    watch_body = '<div class="stock-grid">' + "".join(watch_cards or ["<p>当前没有非持仓关注股。</p>"]) + "</div>"
    main_html = "".join(
        [
            _today_script_html(snapshot),
            _market_thermometer_html(snapshot),
            _action_matrix_html(position_actions, positions, watchlist),
            _collapsible_section_html(
                section_id="positions",
                title="持仓诊断",
                eyebrow=f"{len(positions)} 只 · 默认展开",
                body_html=position_body,
                open_by_default=True,
            ),
            _collapsible_section_html(
                section_id="watchlist-tracking",
                title="关注池技术跟踪",
                eyebrow=f"{len(watchlist)} 只 · 默认收起",
                body_html=watch_body,
                open_by_default=False,
            ),
            _data_appendix_html(snapshot),
        ]
    )
    html_report = _html_document(now, "l-stock 交易报告", main_html, _gate_status(snapshot), include_nav=True)
    return html_report, len(chart_data_uris)


def render_html_to_file(snapshot: dict[str, Any], output_path: Path) -> dict[str, Any]:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    html_report, chart_count = _render_html_report(snapshot)
    output_path.write_text(html_report, encoding="utf-8")
    return {
        "format": "html",
        "report": str(output_path),
        "gate_status": _gate_status(snapshot),
        "chart_count": chart_count,
        "chart_style": "candlestick" if chart_count else "none",
    }


def _gate_status(snapshot: dict[str, Any]) -> str:
    gate = snapshot.get("gate")
    if isinstance(gate, dict):
        return str(gate.get("status", "UNKNOWN"))
    return "UNKNOWN"


def _chrome_tasks(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_many(value: Any) -> None:
        for task in _as_list(value):
            if not isinstance(task, dict):
                continue
            marker = json.dumps(task, ensure_ascii=False, sort_keys=True)
            if marker not in seen:
                seen.add(marker)
                tasks.append(task)

    add_many(snapshot.get("chrome_tasks"))
    for value in snapshot.values():
        if isinstance(value, dict):
            add_many(value.get("chrome_tasks"))
    return tasks


def _render_blocks(snapshot: dict[str, Any], lines: list[str]) -> None:
    gate = snapshot.get("gate") if isinstance(snapshot.get("gate"), dict) else {}
    blocks = _as_list(gate.get("blocks")) if isinstance(gate, dict) else []
    warns = _as_list(gate.get("warns")) if isinstance(gate, dict) else []

    lines.extend(["## BLOCK 项", ""])
    if not blocks:
        lines.append("- gate.status 为 BLOCK，但未提供 blocks 明细。")
    for block in blocks:
        if not isinstance(block, dict):
            lines.append(f"- {_md_cell(block)}")
            continue
        group = block.get("group", "未知")
        reason = block.get("reason", "blocked")
        missing = block.get("missing", [])
        missing_text = "、".join(str(item) for item in _as_list(missing)) or "未列明"
        lines.append(f"- `{group}`：{reason}；缺失：{missing_text}")
    lines.append("")

    if warns:
        lines.extend(["## WARN 项", ""])
        for warn in warns:
            if not isinstance(warn, dict):
                lines.append(f"- {_md_cell(warn)}")
                continue
            lines.append(f"- `{warn.get('group', '未知')}`：{warn.get('reason', 'warning')}")
        lines.append("")


def _render_chrome_tasks(snapshot: dict[str, Any], lines: list[str]) -> None:
    tasks = _chrome_tasks(snapshot)
    lines.extend(["## Chrome 补数任务", ""])
    if not tasks:
        lines.append("- 未提供 chrome_tasks；先补齐 gate.blocks 中的缺失数据。")
        lines.append("")
        return

    for index, task in enumerate(tasks, start=1):
        group = task.get("group", "unknown")
        name = task.get("name", "补数任务")
        lines.append(f"### {index}. {group}：{name}")
        if task.get("url"):
            lines.append(f"- url: `{task['url']}`")
        if task.get("override_path"):
            lines.append(f"- override_path: `{task['override_path']}`")
        if task.get("override_key"):
            lines.append(f"- override_key: `{task['override_key']}`")
        if task.get("expected_status"):
            lines.append(f"- expected_status: `{task['expected_status']}`")
        if task.get("success_criteria"):
            lines.append(f"- success_criteria: {task['success_criteria']}")
        required_fields = task.get("required_fields")
        if isinstance(required_fields, list):
            fields = ", ".join(f"`{field}`" for field in required_fields)
            lines.append(f"- required_fields: {fields}")
        if "example_override" in task:
            lines.extend(["- example_override:", "", "```json", _json(task["example_override"]), "```"])
        lines.append("")


def render_data_block(snapshot: dict[str, Any]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# l-stock 补数报告：{now}",
        "",
        "数据不足，禁止生成正式买卖建议。",
        "",
        "## 数据闸门",
        "",
        f"- 状态：{_gate_status(snapshot)}",
        "- 处理：先完成补数或确认数据覆盖，再重新渲染正式交易报告。",
        "",
    ]
    _render_blocks(snapshot, lines)
    _render_chrome_tasks(snapshot, lines)
    lines.extend(
        [
            "## 原始证据",
            "",
            f"- gate JSON：`{_inline_json(snapshot.get('gate', {}))}`",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _render_report(snapshot: dict[str, Any], output_path: Optional[Path] = None) -> tuple[str, int]:
    if _gate_status(snapshot) not in {"PASS", "WARN"}:
        return render_data_block(snapshot), 0

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    market = snapshot.get("market") if isinstance(snapshot.get("market"), dict) else {}
    emotion = snapshot.get("emotion") if isinstance(snapshot.get("emotion"), dict) else {}
    position_actions, watch_actions = _collect_actions(snapshot)
    positions, watchlist = _analysis_items(snapshot)
    chart_paths = _prepare_chart_paths(positions, output_path, identity="position", include_trade_plan_levels=True)
    chart_paths.update(_prepare_chart_paths(watchlist, output_path, identity="watch", include_trade_plan_levels=False))

    lines = [
        f"# l-stock 交易报告：{now}",
        "",
        "## 交易摘要",
        "",
        "### 今日结论",
        f"- 策略：{market.get('stance', '观察')}为主；推断：{_market_inference(snapshot)}",
        f"- 根据：{_market_index_summary(market)}；{_emotion_summary(emotion)}",
        f"- 主线：{_sector_summary(snapshot)}",
        f"- 预备现金：{_reserve_cash_line(snapshot)}",
        "",
    ]
    _append_market_evidence(lines, snapshot)
    _append_execution_summary(lines, position_actions, watch_actions)
    _append_stock_playbooks(lines, snapshot, position_actions, watch_actions, chart_paths)
    _append_action_table(lines, position_actions, watch_actions)
    lines.extend(
        [
            "## 诊断证据",
            "",
            f"- 数据闸门：{_gate_status(snapshot)}",
            f"- market JSON（摘要）：`{_inline_json(_compact_group(market))}`",
            f"- emotion JSON（摘要）：`{_inline_json(_compact_group(emotion))}`",
        ]
    )
    return "\n".join(lines).rstrip() + "\n", len(chart_paths)


def render(snapshot: dict[str, Any]) -> str:
    markdown, _chart_count = _render_report(snapshot)
    return markdown


def render_markdown_to_file(snapshot: dict[str, Any], output_path: Path, include_images: bool = False) -> dict[str, Any]:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    markdown, chart_count = _render_report(snapshot, output_path if include_images else None)
    output_path.write_text(markdown, encoding="utf-8")
    return {
        "format": "markdown",
        "report": str(output_path),
        "gate_status": _gate_status(snapshot),
        "chart_count": chart_count if include_images else 0,
        "chart_style": "candlestick" if include_images and chart_count else "none",
    }


def render_to_file(snapshot: dict[str, Any], output_path: Path) -> dict[str, Any]:
    return render_markdown_to_file(snapshot, output_path, include_images=True)


def _playwright_pdf_runner(report_path: Path, output_path: Path) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as error:
        raise RuntimeError("PDF export requires Python Playwright. HTML report is still available.") from error

    file_url = report_path.resolve().as_uri()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1800}, device_scale_factor=1)
            page.goto(file_url, wait_until="networkidle")
            page.emulate_media(media="print")
            page.evaluate(
                "document.querySelectorAll('details.collapsible, details.playbook-details').forEach(function(section) { "
                "section.setAttribute('open', ''); "
                "});"
            )
            page.pdf(
                path=str(output_path),
                format="A4",
                print_background=True,
                prefer_css_page_size=True,
                margin={"top": "12mm", "right": "10mm", "bottom": "12mm", "left": "10mm"},
            )
        finally:
            browser.close()


def export_pdf_from_html(
    report_path: Path,
    output_path: Path,
    runner: Optional[Callable[[Path, Path], None]] = None,
) -> dict[str, Any]:
    report_path = Path(report_path)
    output_path = Path(output_path)
    if not report_path.is_file():
        raise FileNotFoundError(f"HTML report not found: {report_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_runner = runner or _playwright_pdf_runner
    pdf_runner(report_path, output_path)
    if not output_path.is_file():
        raise RuntimeError(f"PDF export did not create output: {output_path}")
    if output_path.stat().st_size <= 0:
        raise RuntimeError(f"PDF export produced invalid PDF output: {output_path}")
    with output_path.open("rb") as pdf_file:
        if not pdf_file.read(5).startswith(b"%PDF-"):
            raise RuntimeError(f"PDF export produced invalid PDF output: {output_path}")
    return {
        "format": "pdf",
        "report": str(report_path),
        "pdf": str(output_path),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = JsonArgumentParser(description="Render and export l-stock reports")
    subcommands = parser.add_subparsers(dest="command", required=True, parser_class=JsonArgumentParser)

    html_parser = subcommands.add_parser("render-html", help="render an HTML report from a snapshot JSON file")
    html_parser.add_argument("--snapshot", required=True, help="path to snapshot JSON")
    html_parser.add_argument("--output", required=True, help="path to HTML report output")

    markdown_parser = subcommands.add_parser("render-md", help="render a clean Markdown report from a snapshot JSON file")
    markdown_parser.add_argument("--snapshot", required=True, help="path to snapshot JSON")
    markdown_parser.add_argument("--output", required=True, help="path to Markdown report output")
    markdown_parser.add_argument("--with-images", action="store_true", help="include generated chart images")

    render_parser = subcommands.add_parser("render", help="legacy alias for Markdown report with generated images")
    render_parser.add_argument("--snapshot", required=True, help="path to snapshot JSON")
    render_parser.add_argument("--output", required=True, help="path to Markdown report output")

    pdf_parser = subcommands.add_parser("export-pdf", help="export a rendered HTML report to PDF")
    pdf_parser.add_argument("--report", required=True, help="path to rendered HTML report")
    pdf_parser.add_argument("--output", required=True, help="path to PDF output")

    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)

        if args.command == "export-pdf":
            payload = export_pdf_from_html(Path(args.report), Path(args.output))
        else:
            snapshot_path = Path(args.snapshot)
            output_path = Path(args.output)
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            if not isinstance(snapshot, dict):
                raise ValueError(f"{snapshot_path} must contain a JSON object")

            if args.command == "render-html":
                payload = render_html_to_file(snapshot, output_path)
            elif args.command == "render-md":
                payload = render_markdown_to_file(snapshot, output_path, include_images=args.with_images)
            elif args.command == "render":
                payload = render_markdown_to_file(snapshot, output_path, include_images=True)
            else:
                raise ValueError(f"Unknown command: {args.command}")

        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        print(json.dumps({"status": "ERROR", "error": str(error)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
