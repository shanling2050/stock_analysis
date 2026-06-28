#!/usr/bin/env python3
"""Market data helpers, indicators, and data gate for l-stock."""

import argparse
import importlib.util
import json
import re
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional


REQUIRED_GROUPS = ["state", "market", "stocks", "funds", "sectors", "emotion"]
REQUIRED_STATE_FILES = ["positions.yaml", "watchlist.yaml", "preferences.yaml", "history.yaml"]
MA_WINDOWS = (5, 10, 20, 40, 60)
EASTMONEY_KLINE_SOURCE = "eastmoney_kline"
SINA_KLINE_SOURCE = "sina_kline"
TENCENT_KLINE_SOURCE = "tencent_kline"
TENCENT_HK_KLINE_SOURCE = "tencent_hk_kline"
VALID_GROUP_STATUSES = {"PASS", "WARN", "BLOCK"}
SOURCE_OVERRIDE_PATH = "cache/run_logs/source-overrides.json"
MARKET_SECURITIES = [
    {"code": "000300", "name": "沪深300", "secid": "1.000300"},
    {"code": "000905", "name": "中证500", "secid": "1.000905"},
    {"code": "399006", "name": "创业板指", "secid": "0.399006"},
]
MARKET_INDEX_CODES = [item["code"] for item in MARKET_SECURITIES]
MIN_MATERIAL_FUND_FLOW_BILLION = 0.5
MIN_MATERIAL_FUND_FLOW_RATIO = 0.01
CHROME_OVERRIDE_DETAILS: dict[str, dict[str, Any]] = {
    "market": {
        "required_fields": [
            "status",
            "source",
            "items[].code",
            "items[].name",
            "items[].close",
            "items[].ma10",
            "items[].ma30",
        ],
        "example_override": {
            "status": "PASS",
            "source": "chrome",
            "items": [
                {
                    "code": "000300",
                    "name": "沪深300",
                    "close": 3810.5,
                    "ma10": 3760.2,
                    "ma30": 3688.4,
                },
                {
                    "code": "000905",
                    "name": "中证500",
                    "close": 5680.3,
                    "ma10": 5620.1,
                    "ma30": 5510.7,
                },
                {
                    "code": "399006",
                    "name": "创业板指",
                    "close": 2050.2,
                    "ma10": 2018.5,
                    "ma30": 1988.6,
                }
            ],
        },
        "success_criteria": "确认指数代码、名称、收盘价、MA10、MA30 来自最新行情/K线页面后，写入 PASS 覆盖。",
    },
    "stocks": {
        "required_fields": [
            "status",
            "source",
            "items[].code",
            "items[].name",
            "items[].close",
            "items[].ma10",
            "items[].ma30",
        ],
        "example_override": {
            "status": "PASS",
            "source": "chrome",
            "items": [
                {
                    "code": "600183",
                    "name": "生益科技",
                    "close": 28.4,
                    "ma20": 27.8,
                    "ma40": 26.9,
                }
            ],
        },
        "success_criteria": "确认每只持仓/关注股票的代码、名称、收盘价、MA20、MA40 均来自最新行情/K线页面后，写入 PASS 覆盖。",
    },
    "funds": {
        "required_fields": [
            "status",
            "source",
            "items[].code",
            "items[].name",
            "items[].scale_change_billion",
            "items[].scale_billion",
            "items[].turnover",
        ],
        "example_override": {
            "status": "PASS",
            "source": "chrome",
            "items": [
                {
                    "code": "510300",
                    "name": "沪深300ETF",
                    "scale_change_billion": -7.0,
                    "scale_billion": 1200.0,
                    "turnover": "12.3亿",
                }
            ],
        },
        "success_criteria": "确认 ETF 代码、名称、规模变化、规模和成交额均来自页面最新表格后，写入 PASS 覆盖。",
    },
    "sectors": {
        "required_fields": [
            "status",
            "source",
            "items[].name",
            "items[].change_pct",
            "items[].main_net_inflow",
            "items[].super_large_net_inflow",
        ],
        "example_override": {
            "status": "PASS",
            "source": "chrome",
            "items": [
                {
                    "name": "电子",
                    "change_pct": 1.23,
                    "main_net_inflow": "12.3亿",
                    "super_large_net_inflow": "4.5亿",
                }
            ],
        },
        "success_criteria": "确认板块涨跌幅、主力净流入和超大单净流入为页面最新行业资金流向数据后，写入 PASS 覆盖。",
    },
    "emotion": {
        "required_fields": [
            "status",
            "source",
            "limit_up_count",
            "break_board_rate",
            "height",
            "leader_performance",
        ],
        "example_override": {
            "status": "PASS",
            "source": "chrome",
            "limit_up_count": 62,
            "break_board_rate": 0.31,
            "height": 5,
            "leader_performance": "高标晋级良好",
        },
        "success_criteria": "确认涨停家数、炸板率、连板高度和龙头表现均来自最新涨停板页面后，写入 PASS 覆盖。",
    },
}


class JsonCliError(Exception):
    """Raised for CLI input errors that should be rendered as JSON."""


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise JsonCliError(message)

    def exit(self, status: int = 0, message: Optional[str] = None) -> None:
        if status:
            raise JsonCliError((message or f"exit status {status}").strip())
        raise SystemExit(status)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def calc_ma(closes: list[Any], windows: Optional[tuple[int, ...]] = None) -> dict[str, float]:
    values = [float(value) for value in closes]
    result: dict[str, float] = {}
    ma_windows = windows if windows is not None else MA_WINDOWS
    for window in ma_windows:
        if len(values) >= window:
            result[f"ma{window}"] = round(statistics.mean(values[-window:]), 4)
    return result


def eastmoney_secid(code: str) -> str:
    normalized = str(code).strip()
    for item in MARKET_SECURITIES:
        if item["code"] == normalized:
            return str(item["secid"])
    if normalized.startswith(("5", "6", "9")):
        return f"1.{normalized}"
    if normalized.startswith("00") and len(normalized) == 6:
        return f"116.{normalized[2:]}"
    return f"0.{normalized}"


def kline_block(code: str, rows: list[dict[str, Any]], reason: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": code,
        "status": "BLOCK",
        "reason": reason,
        "source": EASTMONEY_KLINE_SOURCE,
        "fetched_at": now_iso(),
        "rows": rows,
        "indicators": calc_ma([row["close"] for row in rows]),
    }
    payload.update(extra)
    return payload


def parse_eastmoney_rows(klines: list[Any], days: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in klines[-days:]:
        if not isinstance(item, str):
            continue
        parts = item.split(",")
        if len(parts) < 7:
            continue
        rows.append(
            {
                "date": parts[0],
                "open": float(parts[1]),
                "close": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "volume": float(parts[5]),
                "amount": float(parts[6]),
            }
        )
    return rows


def _request_headers(referer: str = "https://quote.eastmoney.com/") -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": referer,
    }


def _sina_symbol(code: str) -> str:
    normalized = str(code).strip()
    if normalized in {"000300", "000905"}:
        return f"sh{normalized}"
    if normalized == "399006":
        return f"sz{normalized}"
    return ("sh" if normalized.startswith(("5", "6", "9")) else "sz") + normalized


def parse_sina_rows(payload: str, days: int) -> list[dict[str, Any]]:
    match = re.search(r"\((\[.*\])\);?\s*$", payload, re.S)
    if not match:
        raise ValueError("missing Sina JSONP payload")
    raw_rows = json.loads(match.group(1))
    if not isinstance(raw_rows, list):
        raise ValueError("Sina JSONP payload is not a list")

    rows: list[dict[str, Any]] = []
    for item in raw_rows[-days:]:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "date": str(item.get("day") or item.get("date") or ""),
                "open": float(item["open"]),
                "close": float(item["close"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "volume": float(item.get("volume") or 0),
                "amount": float(item.get("amount") or 0),
            }
        )
    return rows


def fetch_sina_kline(code: str, days: int = 120, *, fallback_from: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    normalized = str(code).strip()
    symbol = _sina_symbol(normalized)
    url = (
        "https://quotes.sina.cn/cn/api/jsonp.php/"
        f"var%20_{symbol}_240_/CN_MarketDataService.getKLineData?"
        + urllib.parse.urlencode({"symbol": symbol, "scale": 240, "ma": "no", "datalen": days})
    )
    request = urllib.request.Request(url, headers=_request_headers("https://finance.sina.com.cn/"))
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            rows = parse_sina_rows(response.read().decode("utf-8", errors="replace"), days)
    except (OSError, urllib.error.URLError, json.JSONDecodeError, KeyError, ValueError, TypeError) as error:
        payload = kline_block(normalized, [], "fallback_fetch_error", fallback_from=fallback_from, error=str(error))
        payload["source"] = SINA_KLINE_SOURCE
        return payload

    closes = [row["close"] for row in rows]
    status = "PASS" if len(rows) >= 40 else "BLOCK"
    result: dict[str, Any] = {
        "code": normalized,
        "status": status,
        "source": SINA_KLINE_SOURCE,
        "fetched_at": now_iso(),
        "rows": rows,
        "close": closes[-1] if closes else None,
        "indicators": calc_ma(closes),
    }
    if fallback_from is not None:
        result["fallback_from"] = fallback_from
    if status == "BLOCK":
        result["reason"] = "insufficient_rows"
        result["missing"] = ["kline_rows>=40"]
    return result


def _tencent_symbol(code: str) -> str:
    normalized = str(code).strip()
    if normalized in {"000300", "000905"}:
        return f"sh{normalized}"
    if normalized == "399006":
        return f"sz{normalized}"
    return ("sh" if normalized.startswith(("5", "6", "9")) else "sz") + normalized


def _is_hk_code(code: str) -> bool:
    normalized = str(code).strip()
    if len(normalized) == 5 and normalized.startswith("00"):
        return True
    if len(normalized) == 6 and normalized.startswith("00"):
        return normalized in KNOWN_HK_STOCK_CONNECT_CODES
    return False


KNOWN_HK_CODES = {"00700", "09988", "09999", "09698", "06198", "06098", "06998", "06888", "02382", "02196", "01179", "01359", "01579", "06969"}

KNOWN_HK_STOCK_CONNECT_CODES = {"003441", "001888", "00169", "03333", "06699", "06837", "06030", "06198", "06969", "09698"}


def _is_known_hk_code(code: str) -> bool:
    normalized = str(code).strip()
    return normalized in KNOWN_HK_CODES


def _tencent_hk_symbol(code: str) -> str:
    normalized = str(code).strip()
    return f"hk{normalized.zfill(5)}"


def parse_tencent_rows(data: list[list[str]], days: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in data[-days:]:
        if not isinstance(item, list) or len(item) < 6:
            continue
        try:
            rows.append(
                {
                    "date": str(item[0]),
                    "open": float(item[1]),
                    "close": float(item[2]),
                    "high": float(item[3]),
                    "low": float(item[4]),
                    "volume": float(item[5]),
                    "amount": float(item[5]) if len(item) > 5 else 0.0,
                }
            )
        except (ValueError, TypeError):
            continue
    return rows


def fetch_tencent_kline(code: str, days: int = 120, *, fallback_from: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    normalized = str(code).strip()
    symbol = _tencent_symbol(normalized)
    url = (
        f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?_var=kline_dayqfq&param={symbol},day,2026-01-01,2026-12-31,{days},qfq"
    )
    request = urllib.request.Request(url, headers=_request_headers("https://finance.qq.com/"))
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            text = response.read().decode("utf-8", errors="replace")
            match = re.search(r"=\s*(\{.*\})", text)
            if not match:
                raise ValueError("missing Tencent JSON payload")
            payload = json.loads(match.group(1))
            data = payload.get("data", {})
            stock_data = data.get(symbol, {})
            qfqday = stock_data.get("qfqday", stock_data.get("day", []))
            rows = parse_tencent_rows(qfqday, days)
    except (OSError, urllib.error.URLError, json.JSONDecodeError, KeyError, ValueError, TypeError) as error:
        payload = kline_block(normalized, [], "tencent_fetch_error", fallback_from=fallback_from, error=str(error))
        payload["source"] = TENCENT_KLINE_SOURCE
        return payload

    closes = [row["close"] for row in rows]
    status = "PASS" if len(rows) >= 40 else "BLOCK"
    result: dict[str, Any] = {
        "code": normalized,
        "status": status,
        "source": TENCENT_KLINE_SOURCE,
        "fetched_at": now_iso(),
        "rows": rows,
        "close": closes[-1] if closes else None,
        "indicators": calc_ma(closes),
    }
    if fallback_from is not None:
        result["fallback_from"] = fallback_from
    if status == "BLOCK":
        result["reason"] = "insufficient_rows"
        result["missing"] = ["kline_rows>=40"]
    return result


def fetch_tencent_hk_kline(code: str, days: int = 120, *, fallback_from: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    normalized = str(code).strip()
    symbol = _tencent_hk_symbol(normalized)
    url = (
        f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?_var=kline_dayqfq&param={symbol},day,,,{days},qfq"
    )
    request = urllib.request.Request(url, headers=_request_headers("https://finance.qq.com/"))
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            text = response.read().decode("utf-8", errors="replace")
            match = re.search(r"=\s*(\{.*\})", text)
            if not match:
                raise ValueError("missing Tencent HK JSON payload")
            payload = json.loads(match.group(1))
            data = payload.get("data", {})
            stock_data = data.get(symbol, {})
            qfqday = stock_data.get("qfqday", stock_data.get("day", []))
            rows = parse_tencent_rows(qfqday, days)
    except (OSError, urllib.error.URLError, json.JSONDecodeError, KeyError, ValueError, TypeError) as error:
        payload = kline_block(normalized, [], "tencent_hk_fetch_error", fallback_from=fallback_from, error=str(error))
        payload["source"] = TENCENT_HK_KLINE_SOURCE
        return payload

    closes = [row["close"] for row in rows]
    status = "PASS" if len(rows) >= 40 else "BLOCK"
    result: dict[str, Any] = {
        "code": normalized,
        "status": status,
        "source": TENCENT_HK_KLINE_SOURCE,
        "fetched_at": now_iso(),
        "rows": rows,
        "close": closes[-1] if closes else None,
        "indicators": calc_ma(closes),
    }
    if fallback_from is not None:
        result["fallback_from"] = fallback_from
    if status == "BLOCK":
        result["reason"] = "insufficient_rows"
        result["missing"] = ["kline_rows>=40"]
    return result


def fetch_eastmoney_kline(code: str, days: int = 120, secid: Optional[str] = None) -> dict[str, Any]:
    normalized = str(code).strip()

    if _is_hk_code(normalized) or _is_known_hk_code(normalized):
        return fetch_tencent_hk_kline(normalized, days)

    params = {
        "secid": secid or eastmoney_secid(normalized),
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "1",
        "beg": "20200101",
        "end": "20500101",
    }
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers=_request_headers())

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        fallback_from = kline_block(normalized, [], "fetch_error", error=str(error))
        return fetch_tencent_kline(normalized, days, fallback_from=fallback_from)

    data = payload.get("data")
    if not isinstance(data, dict):
        fallback_from = kline_block(normalized, [], "missing_data")
        return fetch_tencent_kline(normalized, days, fallback_from=fallback_from)

    klines = data.get("klines")
    if not isinstance(klines, list):
        fallback_from = kline_block(normalized, [], "missing_klines")
        return fetch_tencent_kline(normalized, days, fallback_from=fallback_from)

    try:
        rows = parse_eastmoney_rows(klines, days)
    except (ValueError, TypeError) as error:
        fallback_from = kline_block(normalized, [], "parse_error", error=str(error))
        return fetch_tencent_kline(normalized, days, fallback_from=fallback_from)

    closes = [row["close"] for row in rows]
    status = "PASS" if len(rows) >= 40 else "BLOCK"
    result: dict[str, Any] = {
        "code": normalized,
        "status": status,
        "source": EASTMONEY_KLINE_SOURCE,
        "fetched_at": now_iso(),
        "rows": rows,
        "close": closes[-1] if closes else None,
        "indicators": calc_ma(closes),
    }
    if status == "BLOCK":
        fallback = fetch_tencent_kline(normalized, days, fallback_from=result)
        if fallback.get("status") == "PASS":
            return fallback
        fallback2 = fetch_sina_kline(normalized, days, fallback_from=fallback)
        if fallback2.get("status") == "PASS":
            return fallback2
        result["reason"] = "insufficient_rows"
        result["missing"] = ["kline_rows>=40"]
    return result


def fetch_weekly_kline(code: str, weeks: int = 60) -> dict[str, Any]:
    normalized = str(code).strip()
    if _is_hk_code(normalized) or _is_known_hk_code(normalized):
        return fetch_tencent_hk_weekly_kline(normalized, weeks)
    params = {
        "secid": eastmoney_secid(normalized),
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "102",
        "fqt": "1",
        "beg": "20200101",
        "end": "20500101",
    }
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers=_request_headers())
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        return kline_block(normalized, [], "weekly_fetch_error", error=str(error))
    data = payload.get("data")
    if not isinstance(data, dict):
        return kline_block(normalized, [], "weekly_missing_data")
    klines = data.get("klines")
    if not isinstance(klines, list):
        return kline_block(normalized, [], "weekly_missing_klines")
    try:
        rows = parse_eastmoney_rows(klines, weeks)
    except (ValueError, TypeError) as error:
        return kline_block(normalized, [], "weekly_parse_error", error=str(error))
    closes = [row["close"] for row in rows]
    status = "PASS" if len(rows) >= 30 else "BLOCK"
    result: dict[str, Any] = {
        "code": normalized,
        "status": status,
        "source": "eastmoney_weekly",
        "fetched_at": now_iso(),
        "rows": rows,
        "close": closes[-1] if closes else None,
        "indicators": calc_ma(closes, windows=(5, 10, 20, 40)),
    }
    if status == "BLOCK":
        result["reason"] = "insufficient_weekly_rows"
        result["missing"] = ["weekly_rows>=30"]
    return result


def fetch_tencent_hk_weekly_kline(code: str, weeks: int = 60) -> dict[str, Any]:
    normalized = str(code).strip()
    symbol = _tencent_hk_symbol(normalized)
    url = (
        f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?_var=kline_weekqfq&param={symbol},week,,,{weeks},qfq"
    )
    request = urllib.request.Request(url, headers=_request_headers("https://finance.qq.com/"))
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            text = response.read().decode("utf-8", errors="replace")
            match = re.search(r"=\s*(\{.*\})", text)
            if not match:
                raise ValueError("missing Tencent HK weekly JSON payload")
            payload = json.loads(match.group(1))
            data = payload.get("data", {})
            stock_data = data.get(symbol, {})
            qfqweek = stock_data.get("qfqweek", stock_data.get("week", []))
            rows = parse_tencent_rows(qfqweek, weeks)
    except (OSError, urllib.error.URLError, json.JSONDecodeError, KeyError, ValueError, TypeError) as error:
        return kline_block(normalized, [], "tencent_hk_weekly_fetch_error", error=str(error))
    closes = [row["close"] for row in rows]
    status = "PASS" if len(rows) >= 30 else "BLOCK"
    result: dict[str, Any] = {
        "code": normalized,
        "status": status,
        "source": "tencent_hk_weekly",
        "fetched_at": now_iso(),
        "rows": rows,
        "close": closes[-1] if closes else None,
        "indicators": calc_ma(closes, windows=(5, 10, 20, 40)),
    }
    if status == "BLOCK":
        result["reason"] = "insufficient_weekly_rows"
        result["missing"] = ["weekly_rows>=30"]
    return result


def load_json_yaml(path: Path) -> dict[str, Any]:
    """Load JSON-compatible YAML, with optional PyYAML fallback for broader YAML."""
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
                "PyYAML is unavailable for non-JSON YAML fallback"
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


def chrome_task(group: str, name: str, url: str, columns: list[str]) -> dict[str, Any]:
    details = CHROME_OVERRIDE_DETAILS.get(
        group,
        {
            "required_fields": ["status", "source"],
            "example_override": {"status": "PASS", "source": "chrome"},
            "success_criteria": "确认来源数据完整且为最新后，写入 PASS 覆盖。",
        },
    )
    payload = {
        "group": group,
        "name": name,
        "automation_next": "chrome",
        "url": url,
        "columns": columns,
        "override_path": SOURCE_OVERRIDE_PATH,
        "override_key": group,
        "expected_status": "PASS",
        "instruction": f"自动 Python 抓取未完成，下一步由 Codex 打开 Chrome 抓取 {name}。",
    }
    payload.update(details)
    return payload


def blocked_group(reason: str, missing: list[str], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    return {"status": "BLOCK", "reason": reason, "missing": missing, "chrome_tasks": tasks}


def pass_group(data: dict[str, Any]) -> dict[str, Any]:
    payload = {"status": "PASS"}
    payload.update(data)
    return payload


def _request_json(url: str, timeout: int = 10, headers: Optional[dict[str, str]] = None) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers or _request_headers())
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("response JSON is not an object")
    return payload


def _as_number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value in (None, ""):
        return None
    if isinstance(value, str):
        value = value.replace(",", "").replace("%", "").strip()
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _money_to_billion(value: Any) -> Optional[float]:
    parsed = _as_number(value)
    if parsed is None:
        return None
    if abs(parsed) >= 10000:
        parsed = parsed / 100000000
    return round(parsed, 4)


def _money_text(value: Any) -> Optional[str]:
    billion = _money_to_billion(value)
    if billion is None:
        return None
    return f"{billion:.2f}亿"


def _as_billion(value: Any) -> Optional[float]:
    parsed = _as_number(value)
    if parsed is None:
        return None
    return round(parsed, 4)


def _turnover_text(value: Any) -> Optional[str]:
    parsed = _as_number(value)
    if parsed is None:
        return None
    return f"{parsed:g}万"


def _ratio_value(value: Any) -> Optional[float]:
    parsed = _as_number(value)
    if parsed is None:
        return None
    return round(parsed / 100, 4) if parsed > 1 else round(parsed, 4)


def fetch_funds_group_python() -> dict[str, Any]:
    url = "https://www.jisilu.cn/data/etf/etf_list/?___jsl=LST___t=1"
    try:
        payload = _request_json(url)
        rows = payload.get("rows")
        if not isinstance(rows, list):
            raise ValueError("missing rows")

        items: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            cell = row.get("cell") if isinstance(row.get("cell"), dict) else row
            code = str(_first_present(cell.get("fund_id"), cell.get("code"), cell.get("f12")) or "").strip()
            name = str(_first_present(cell.get("fund_nm"), cell.get("name"), cell.get("f14")) or "").strip()
            scale_change = _as_billion(
                _first_present(
                    cell.get("scale_change_billion"),
                    cell.get("scale_incr"),
                    cell.get("fund_size_incr"),
                    cell.get("fund_size_increase"),
                    cell.get("unit_incr"),
                )
            )
            scale = _as_billion(
                _first_present(cell.get("scale_billion"), cell.get("fund_size"), cell.get("unit_total"), cell.get("f20"))
            )
            turnover = _first_present(cell.get("turnover"), cell.get("volume"), cell.get("amount"), cell.get("f6"))
            turnover_text = str(turnover).strip() if isinstance(turnover, str) and any(unit in turnover for unit in ("万", "亿")) else _turnover_text(turnover)
            if not code or not name or scale_change is None or scale is None or not turnover_text:
                continue
            items.append(
                {
                    "code": code,
                    "name": name,
                    "scale_change_billion": scale_change,
                    "scale_billion": scale,
                    "turnover": turnover_text,
                }
            )

        if not items:
            raise ValueError("no valid ETF rows")
        return pass_group({"source": "python:jisilu", "items": items[:30]})
    except Exception as error:
        payload = blocked_group("python_fetch_failed", ["etf_scale_change"], [])
        payload["error"] = str(error)
        return payload


def fetch_sectors_group_python() -> dict[str, Any]:
    params = urllib.parse.urlencode(
        {
            "pn": 1,
            "pz": 30,
            "po": 1,
            "np": 1,
            "fltt": 2,
            "invt": 2,
            "fid": "f62",
            "fs": "m:90+t:2",
            "fields": "f12,f14,f3,f62,f66",
        }
    )
    urls = [
        "https://push2.eastmoney.com/api/qt/clist/get?" + params,
        "http://push2.eastmoney.com/api/qt/clist/get?" + params,
    ]
    try:
        last_error: Optional[Exception] = None
        payload: dict[str, Any] = {}
        for url in urls:
            try:
                payload = _request_json(url, headers=_request_headers("https://data.eastmoney.com/bkzj/hy.html"))
                break
            except Exception as error:
                last_error = error
        else:
            raise last_error or ValueError("sector fetch failed")

        data = payload.get("data")
        diff = data.get("diff") if isinstance(data, dict) else None
        if not isinstance(diff, list):
            raise ValueError("missing sector diff")

        items: list[dict[str, Any]] = []
        for row in diff:
            if not isinstance(row, dict):
                continue
            name = str(row.get("f14") or row.get("name") or "").strip()
            change_pct = _as_number(row.get("f3"))
            main = _money_text(row.get("f62"))
            super_large = _money_text(row.get("f66"))
            if not name or change_pct is None or not main or not super_large:
                continue
            items.append(
                {
                    "name": name,
                    "change_pct": change_pct,
                    "main_net_inflow": main,
                    "super_large_net_inflow": super_large,
                }
            )

        if not items:
            raise ValueError("no valid sector rows")
        return pass_group({"source": "python:eastmoney_sector_flow", "items": items})
    except Exception as error:
        payload = blocked_group("python_fetch_failed", ["sector_flow"], [])
        payload["error"] = str(error)
        return payload


SECTOR_FLOW_KEYWORDS = ["半导体", "电子", "服务器", "CPO", "PCB", "创新药", "保险", "煤炭", "银行", "有色", "贵金属"]
SECTOR_FLOW_EXCLUDE = ["军工电子", "军工", "焦煤", "医美服务", "电子纸概念", "电子车牌", "电子后视镜"]

SECTOR_ALIAS_MAP = {
    "创新药": ["创新药", "生物制品", "化学制药", "医药", "医美"],
    "保险": ["保险", "保险服务"],
    "煤炭": ["煤炭", "焦煤"],
    "银行": ["银行"],
    "有色": ["有色", "有色金属", "稀土", "铜", "铝", "钼"],
    "贵金属": ["贵金属", "黄金"],
    "半导体": ["半导体", "集成电路", "芯片"],
    "电子": ["电子", "光学光电子", "消费电子"],
}

INDUSTRY_SECTOR_BK_CODES = {
    "银行": "BK0475",
    "保险": "BK0474",
    "煤炭开采": "BK0481",
}


def _fetch_eastmoney_sectors(fs: str) -> Optional[list[dict[str, Any]]]:
    params = urllib.parse.urlencode(
        {
            "pn": 1,
            "pz": 200,
            "po": 1,
            "np": 1,
            "fltt": 2,
            "invt": 2,
            "fid": "f62",
            "fs": fs,
            "fields": "f12,f14,f3,f62,f66",
        }
    )
    urls = [
        "https://push2.eastmoney.com/api/qt/clist/get?" + params,
        "http://push2.eastmoney.com/api/qt/clist/get?" + params,
    ]
    for url in urls:
        try:
            payload = _request_json(url, headers=_request_headers("https://data.eastmoney.com/bkzj/hy.html"))
            data = payload.get("data")
            diff = data.get("diff") if isinstance(data, dict) else None
            if isinstance(diff, list):
                return diff
        except Exception:
            continue
    return None


def _fetch_industry_sector_flow(bk_code: str, sector_name: str) -> Optional[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {
            "pn": 1,
            "pz": 100,
            "po": 1,
            "np": 1,
            "fltt": 2,
            "invt": 2,
            "fid": "f62",
            "fs": f"b:{bk_code}",
            "fields": "f12,f14,f3,f62,f66",
        }
    )
    urls = [
        "https://push2.eastmoney.com/api/qt/clist/get?" + params,
        "http://push2.eastmoney.com/api/qt/clist/get?" + params,
    ]
    
    for url in urls:
        try:
            payload = _request_json(url, headers=_request_headers("https://data.eastmoney.com/bkzj/hy.html"))
            data = payload.get("data")
            diff = data.get("diff") if isinstance(data, dict) else None
            if not isinstance(diff, list) or len(diff) == 0:
                continue
            
            total_main = 0.0
            total_super_large = 0.0
            total_change_pct = 0.0
            count = 0
            
            for row in diff:
                if not isinstance(row, dict):
                    continue
                main_val = _as_number(row.get("f62"))
                super_large_val = _as_number(row.get("f66"))
                change_pct_val = _as_number(row.get("f3"))
                
                if main_val is not None and super_large_val is not None:
                    total_main += main_val
                    total_super_large += super_large_val
                    if change_pct_val is not None:
                        total_change_pct += change_pct_val
                        count += 1
            
            if count == 0:
                continue
            
            avg_change_pct = total_change_pct / count if count > 0 else 0.0
            
            return {
                "name": sector_name,
                "change_pct": round(avg_change_pct, 2),
                "main_net_inflow": _money_text(total_main),
                "super_large_net_inflow": _money_text(total_super_large),
            }
        except Exception:
            continue
    
    return None


def fetch_sector_flow_python() -> dict[str, Any]:
    all_sectors: list[dict[str, Any]] = []
    fs_options = ["m:90+t:2", "m:90+t:3", "m:90+t:1"]
    
    for fs in fs_options:
        sectors = _fetch_eastmoney_sectors(fs)
        if sectors:
            all_sectors.extend(sectors)

    seen_names: set[str] = set()
    matched_items: list[dict[str, Any]] = []
    top_items: list[dict[str, Any]] = []
    
    for row in all_sectors:
        if not isinstance(row, dict):
            continue
        name = str(row.get("f14") or row.get("name") or "").strip()
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        
        change_pct = _as_number(row.get("f3"))
        main = _money_text(row.get("f62"))
        super_large = _money_text(row.get("f66"))
        if change_pct is None or not main or not super_large:
            continue
        
        item = {
            "name": name,
            "change_pct": change_pct,
            "main_net_inflow": main,
            "super_large_net_inflow": super_large,
        }
        
        if any(exclude in name for exclude in SECTOR_FLOW_EXCLUDE):
            continue
        
        matched = False
        for keyword in SECTOR_FLOW_KEYWORDS:
            aliases = SECTOR_ALIAS_MAP.get(keyword, [keyword])
            if any(alias in name for alias in aliases):
                matched_items.append(item)
                matched = True
                break
        
        if not matched and len(top_items) < 10:
            top_items.append(item)

    for sector_name, bk_code in INDUSTRY_SECTOR_BK_CODES.items():
        if sector_name in seen_names:
            continue
        industry_flow = _fetch_industry_sector_flow(bk_code, sector_name)
        if industry_flow:
            matched_items.append(industry_flow)
            seen_names.add(sector_name)

    items = matched_items
    note = ""
    if not matched_items:
        items = top_items[:10]
        note = "未匹配到指定板块，显示全市场资金流向靠前板块"
    elif len(matched_items) < len(SECTOR_FLOW_KEYWORDS):
        note = f"已匹配{len(matched_items)}个板块，部分行业板块数据未覆盖"
    
    return pass_group({"source": "python:eastmoney_sector_flow", "items": items, "note": note})


def fetch_margin_group_python() -> dict[str, Any]:
    try:
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPTA_WEB_RZRQ_MRTJ&columns=ALL&pageNumber=1&pageSize=1&sortTypes=-1&sortColumns=DimDate&source=WEB&client=WEB"
        payload = _request_json(url, headers=_request_headers("https://data.eastmoney.com/"))
        data = payload.get("result")
        if isinstance(data, dict):
            records = data.get("data")
            if isinstance(records, list) and len(records) > 0:
                latest = records[0]
                balance = _as_number(latest.get("finBalance"))
                balance_text = f"{round((balance or 0) / 100000000, 2)}亿" if balance else None
                margin_ratio = _as_number(latest.get("finBalanceRate"))
                return pass_group({
                    "source": "python:eastmoney_margin",
                    "balance": balance,
                    "balance_text": balance_text,
                    "margin_ratio": margin_ratio,
                })
        raise ValueError("no margin data in response")
    except Exception as error:
        payload = blocked_group("python_fetch_failed", ["market_margin"], [])
        payload["error"] = str(error)
        return payload


def fetch_northbound_flow_python() -> dict[str, Any]:
    try:
        url = "https://push2.eastmoney.com/api/qt/stock/ffk-day/get?lmt=0&klt=1&secid=1.000300&fields1=f1,f2,f3,f7&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63"
        payload = _request_json(url, headers=_request_headers("https://quote.eastmoney.com/"))
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("missing northbound data")
        diff = data.get("diff")
        if not isinstance(diff, list):
            raise ValueError("missing northbound diff")
        recent_flows = []
        for row in diff[-5:]:
            if not isinstance(row, dict):
                continue
            date = str(row.get("f51", ""))
            net_buy = _as_number(row.get("f56"))
            if date and net_buy is not None:
                recent_flows.append({"date": date, "net_buy": net_buy, "net_buy_text": f"{round(net_buy / 100000000, 2)}亿"})
        if not recent_flows:
            raise ValueError("no valid northbound flow data")
        total_net_buy = sum(f.get("net_buy", 0) for f in recent_flows)
        consecutive_sell_days = sum(1 for f in recent_flows if f.get("net_buy", 0) < 0)
        return pass_group({
            "source": "python:eastmoney_northbound",
            "flows": recent_flows,
            "total_net_buy": total_net_buy,
            "total_net_buy_text": f"{round(total_net_buy / 100000000, 2)}亿",
            "consecutive_sell_days": consecutive_sell_days,
        })
    except Exception as error:
        payload = blocked_group("python_fetch_failed", ["northbound_flow"], [])
        payload["error"] = str(error)
        return payload


LEADER_STOCK_CODES = ["603986", "688012", "688008", "688981", "300502"]


def _china_yyyymmdd() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")


def _recent_china_dates(days: int = 10) -> list[str]:
    today = datetime.now(timezone(timedelta(hours=8))).date()
    return [(today - timedelta(days=offset)).strftime("%Y%m%d") for offset in range(days)]


def _fetch_eastmoney_topic_pool(endpoint: str, date: str, pagesize: int = 1000) -> dict[str, Any]:
    params = urllib.parse.urlencode(
        {
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "dpt": "wz.ztzt",
            "Pageindex": 0,
            "pagesize": pagesize,
            "sort": "fbt:asc",
            "date": date,
        }
    )
    return _request_json(
        "https://push2ex.eastmoney.com/" + endpoint + "?" + params,
        headers=_request_headers("https://quote.eastmoney.com/ztb/"),
    )


def fetch_emotion_group_python() -> dict[str, Any]:
    try:
        last_error: Optional[Exception] = None
        trade_date = _china_yyyymmdd()
        data: dict[str, Any] = {}
        pool: list[Any] = []
        for candidate_date in _recent_china_dates():
            try:
                payload = _fetch_eastmoney_topic_pool("getTopicZTPool", candidate_date)
                candidate_data = payload.get("data")
                if not isinstance(candidate_data, dict):
                    raise ValueError("missing emotion data")
                candidate_pool = candidate_data.get("pool")
                if not isinstance(candidate_pool, list):
                    raise ValueError("missing limit-up pool")
                candidate_count = _as_number(_first_present(candidate_data.get("tc"), candidate_data.get("count")))
                if candidate_pool or (candidate_count is not None and candidate_count > 0):
                    trade_date = candidate_date
                    data = candidate_data
                    pool = candidate_pool
                    break
                last_error = ValueError(f"empty limit-up pool for {candidate_date}")
            except Exception as error:
                last_error = error
        else:
            raise last_error or ValueError("missing emotion data")

        limit_up_count = _as_number(_first_present(data.get("tc"), data.get("count")))
        if limit_up_count is None:
            limit_up_count = float(len(pool))
        heights = [_as_number(row.get("lbc") if isinstance(row, dict) else None) for row in pool]
        height_values = [value for value in heights if value is not None]
        height = max(height_values) if height_values else 1.0
        break_payload = _fetch_eastmoney_topic_pool("getTopicZBPool", trade_date)
        break_data = break_payload.get("data")
        if not isinstance(break_data, dict):
            raise ValueError("missing break-board data")
        break_count = _as_number(_first_present(break_data.get("tc"), break_data.get("count")))
        if break_count is None:
            break_pool = break_data.get("pool")
            break_count = float(len(break_pool)) if isinstance(break_pool, list) else 0.0
        denominator = float(limit_up_count) + float(break_count)
        break_board_rate = round(float(break_count) / denominator, 4) if denominator > 0 else 0.0
        leader_name = ""
        for row in pool:
            if isinstance(row, dict) and _as_number(row.get("lbc")) == height:
                leader_name = str(row.get("n") or row.get("name") or "").strip()
                break
        leader_performance = f"连板高度 {int(height)}" + (f"，代表 {leader_name}" if leader_name else "")
        return pass_group(
            {
                "source": "python:eastmoney_zt_pool",
                "trade_date": trade_date,
                "limit_up_count": int(limit_up_count),
                "break_board_rate": break_board_rate,
                "height": int(height),
                "leader_performance": leader_performance,
            }
        )
    except Exception as error:
        payload = blocked_group("python_fetch_failed", ["limit_up_stats"], [])
        payload["error"] = str(error)
        return payload


def _with_chrome_fallback(
    fetched: dict[str, Any],
    task: dict[str, Any],
    fallback_reason: str,
    missing: list[str],
) -> dict[str, Any]:
    if fetched.get("status") == "PASS":
        return fetched
    payload = dict(fetched) if isinstance(fetched, dict) else {}
    payload.update(
        {
            "status": "BLOCK",
            "reason": payload.get("reason", fallback_reason),
            "missing": payload.get("missing", missing),
            "chrome_tasks": [task],
        }
    )
    return payload


def _load_lstock_state_module() -> Any:
    try:
        import lstock_state  # type: ignore

        return lstock_state
    except ModuleNotFoundError:
        state_path = Path(__file__).with_name("lstock_state.py")
        spec = importlib.util.spec_from_file_location("lstock_state", state_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to load state validator from {state_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def _state_validation_missing(errors: list[Any]) -> list[str]:
    missing: list[str] = []
    for error in errors:
        if not isinstance(error, dict):
            continue
        files = error.get("files")
        if isinstance(files, list):
            missing.extend(str(item) for item in files)
            continue
        file_name = error.get("file")
        key = error.get("key")
        if file_name and key:
            missing.append(f"{file_name}:{key}")
        elif file_name:
            missing.append(str(file_name))

    deduped: list[str] = []
    for item in missing:
        if item not in deduped:
            deduped.append(item)
    return deduped


def collect_state_group(workspace: Path) -> dict[str, Any]:
    workspace = Path(workspace)
    state_root = Path(workspace) / "state"
    missing = [name for name in REQUIRED_STATE_FILES if not (state_root / name).is_file()]

    try:
        validation = _load_lstock_state_module().validate_state(workspace)
    except Exception as error:
        validation = {
            "status": "BLOCK",
            "errors": [{"type": "state_validation_error", "message": str(error)}],
        }

    if validation.get("status") == "BLOCK":
        errors = validation.get("errors", [])
        if not isinstance(errors, list):
            errors = [{"type": "invalid_validator_response", "errors": errors}]
        payload = blocked_group("invalid_state", missing or _state_validation_missing(errors), [])
        payload["errors"] = errors
        return payload

    try:
        positions_data = load_json_yaml(state_root / "positions.yaml")
        watchlist_data = load_json_yaml(state_root / "watchlist.yaml")
        preferences_data = load_json_yaml(state_root / "preferences.yaml")
        history_data = load_json_yaml(state_root / "history.yaml")
    except (OSError, ValueError) as error:
        payload = blocked_group("invalid_state", [str(error)], [])
        payload["errors"] = [{"type": "unreadable_state", "message": str(error)}]
        return payload

    positions = positions_data.get("positions", [])
    watchlist = watchlist_data.get("watchlist", [])
    if not isinstance(positions, list):
        payload = blocked_group("invalid_state", ["positions"], [])
        payload["errors"] = [{"type": "invalid_state_shape", "file": "positions.yaml", "key": "positions"}]
        return payload
    if not isinstance(watchlist, list):
        payload = blocked_group("invalid_state", ["watchlist"], [])
        payload["errors"] = [{"type": "invalid_state_shape", "file": "watchlist.yaml", "key": "watchlist"}]
        return payload

    return pass_group(
        {
            "positions": positions,
            "watchlist": watchlist,
            "preferences": preferences_data,
            "history": history_data,
        }
    )


def _collect_codes(items: list[Any]) -> list[str]:
    codes: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        code = item.get("code")
        if code is None:
            continue
        normalized = str(code).strip()
        if normalized and normalized not in codes:
            codes.append(normalized)
    return codes


def _source_summary(items: list[dict[str, Any]], default: str) -> str:
    sources = sorted(
        {
            str(item.get("source"))
            for item in items
            if isinstance(item, dict) and item.get("status") != "BLOCK" and item.get("source")
        }
    )
    if not sources:
        return default
    if len(sources) == 1:
        return sources[0]
    return "mixed:" + "+".join(sources)


def collect_stock_group(workspace: Path, offline: bool, state: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    state = state if isinstance(state, dict) else collect_state_group(Path(workspace))
    if state.get("status") == "BLOCK":
        return blocked_group("state_unavailable", state.get("missing", ["positions", "watchlist"]), [])

    codes = _collect_codes(state.get("positions", []) + state.get("watchlist", []))
    if not codes:
        return pass_group({"items": []})
    if offline:
        return blocked_group("offline_mode", codes, [])

    items: list[dict[str, Any]] = []
    missing: list[str] = []
    for code in codes:
        try:
            item = fetch_eastmoney_kline(code)
        except Exception as error:
            item = {
                "code": code,
                "status": "BLOCK",
                "reason": "fetch_exception",
                "error": str(error),
            }
            missing.append(code)
        else:
            if not isinstance(item, dict) or item.get("status") == "BLOCK":
                missing.append(code)
        items.append(item)

    if missing:
        return {"status": "BLOCK", "reason": "kline_fetch_failed", "missing": missing, "items": items}
    return pass_group({"source": _source_summary(items, EASTMONEY_KLINE_SOURCE), "items": items})


def collect_market_group(offline: bool) -> dict[str, Any]:
    if offline:
        return blocked_group("offline_mode", MARKET_INDEX_CODES, [])

    items: list[dict[str, Any]] = []
    missing: list[str] = []
    for security in MARKET_SECURITIES:
        code = security["code"]
        try:
            item = fetch_eastmoney_kline(code, days=80, secid=str(security["secid"]))
        except Exception as error:
            item = {
                "code": code,
                "status": "BLOCK",
                "reason": "fetch_exception",
                "error": str(error),
            }
            missing.append(code)
        else:
            if isinstance(item, dict):
                item.setdefault("name", security["name"])
                item.setdefault("secid", security["secid"])
            if not isinstance(item, dict) or item.get("status") == "BLOCK":
                missing.append(code)
        items.append(item)

    if missing:
        return {"status": "BLOCK", "reason": "index_kline_fetch_failed", "missing": missing, "items": items}
    return pass_group({"source": _source_summary(items, EASTMONEY_KLINE_SOURCE), "items": items})


def _fallback_group_with_tasks(group: dict[str, Any], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    payload = dict(group)
    if payload.get("status") == "BLOCK" and tasks:
        payload["chrome_tasks"] = tasks
    return payload


def collect_kline_fallback_groups(market_group: dict[str, Any], stock_group: dict[str, Any]) -> dict[str, Any]:
    market_task = chrome_task(
        "market",
        "指数 K 线与均线",
        "https://quote.eastmoney.com/center/hszs.html",
        ["代码", "名称", "收盘价", "MA20", "MA40"],
    )
    stock_task = chrome_task(
        "stocks",
        "持仓/关注股 K 线与均线",
        "https://quote.eastmoney.com/",
        ["代码", "名称", "收盘价", "MA20", "MA40"],
    )
    market_tasks = [market_task] if market_group.get("status") == "BLOCK" else []
    stock_tasks = (
        [stock_task]
        if stock_group.get("status") == "BLOCK" and stock_group.get("reason") != "state_unavailable"
        else []
    )
    return {
        "market": _fallback_group_with_tasks(market_group, market_tasks),
        "stocks": _fallback_group_with_tasks(stock_group, stock_tasks),
        "chrome_tasks": market_tasks + stock_tasks,
    }


def collect_hard_source_groups(offline: bool = True) -> dict[str, Any]:
    funds_task = chrome_task(
        "funds",
        "ETF 规模变化",
        "https://www.jisilu.cn/data/etf/",
        ["代码", "名称", "规模变化(亿元)", "规模(亿元)", "成交额"],
    )
    sectors_task = chrome_task(
        "sectors",
        "板块资金流向",
        "https://data.eastmoney.com/bkzj/hy.html",
        ["板块名称", "涨跌幅", "主力净流入", "超大单净流入"],
    )
    emotion_task = chrome_task(
        "emotion",
        "涨停家数/炸板率/连板高度",
        "https://quote.eastmoney.com/ztb/",
        ["涨停家数", "炸板率", "连板高度", "龙头表现"],
    )
    if offline:
        funds = blocked_group("offline_mode", ["etf_scale_change"], [funds_task])
        sectors = blocked_group("offline_mode", ["sector_flow"], [sectors_task])
        emotion = blocked_group("offline_mode", ["limit_up_stats"], [emotion_task])
    else:
        funds = _with_chrome_fallback(fetch_funds_group_python(), funds_task, "python_fetch_failed", ["etf_scale_change"])
        sectors = _with_chrome_fallback(fetch_sectors_group_python(), sectors_task, "python_fetch_failed", ["sector_flow"])
        emotion = _with_chrome_fallback(fetch_emotion_group_python(), emotion_task, "python_fetch_failed", ["limit_up_stats"])

    chrome_tasks = []
    for group in (funds, sectors, emotion):
        tasks = group.get("chrome_tasks") if isinstance(group, dict) else None
        if isinstance(tasks, list):
            chrome_tasks.extend(task for task in tasks if isinstance(task, dict))

    return {"funds": funds, "sectors": sectors, "emotion": emotion, "chrome_tasks": chrome_tasks}


def load_source_overrides(workspace: Path) -> dict[str, Any]:
    path = Path(workspace) / "cache" / "run_logs" / "source-overrides.json"
    if not path.exists():
        return {}

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"{path} could not be read: {error}") from error

    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"{path} is invalid JSON: {error.msg} at line {error.lineno}, column {error.colno}"
        ) from error
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return loaded


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return False
    return parsed == parsed and parsed not in (float("inf"), float("-inf"))


def _is_valid_code(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 6 and value.isdigit()


def _is_valid_required_value(field: str, value: Any) -> bool:
    leaf = field.split("[].")[-1]
    if leaf in {"status", "source", "name", "leader_performance", "turnover", "main_net_inflow", "super_large_net_inflow"}:
        return isinstance(value, str) and bool(value.strip())
    if leaf == "code":
        return _is_valid_code(value)
    if leaf in {
        "scale_change_billion",
        "scale_billion",
        "change_pct",
        "limit_up_count",
        "break_board_rate",
        "height",
        "close",
        "ma20",
        "ma40",
    }:
        return _is_finite_number(value)
    return not _is_blank(value)


def _missing_required_override_fields(
    group: str,
    source_group: dict[str, Any],
    expected_codes: Optional[list[str]] = None,
) -> list[str]:
    required_fields = CHROME_OVERRIDE_DETAILS.get(group, {}).get("required_fields", [])
    missing: list[str] = []
    item_fields_by_root: dict[str, list[tuple[str, str]]] = {}

    for field in required_fields:
        if "[]." in field:
            root, item_field = field.split("[].", 1)
            item_fields_by_root.setdefault(root, []).append((field, item_field))
        elif field not in source_group or not _is_valid_required_value(field, source_group.get(field)):
            missing.append(field)

    # Policy: array-backed override fields must be present and valid on every item.
    # This keeps mixed complete/incomplete browser scrapes from silently passing.
    item_codes: set[str] = set()
    for root, item_fields in item_fields_by_root.items():
        items = source_group.get(root)
        if not isinstance(items, list) or not items:
            missing.append(root)
            missing.extend(full_field for full_field, _item_field in item_fields)
            continue

        for item in items:
            if isinstance(item, dict) and _is_valid_code(item.get("code")):
                item_codes.add(str(item["code"]))

        for full_field, item_field in item_fields:
            if any(
                not isinstance(item, dict)
                or item_field not in item
                or not _is_valid_required_value(item_field, item.get(item_field))
                for item in items
            ):
                missing.append(full_field)

    for code in expected_codes or []:
        if code not in item_codes:
            missing.append(f"items[].code:{code}")

    return _dedupe(missing)


def _invalid_source_override_group(
    group: str,
    source_group: Any,
    hard: dict[str, Any],
    missing: list[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tasks = hard[group].get("chrome_tasks", [])
    payload = blocked_group("invalid_source_override", missing, tasks)
    if isinstance(source_group, dict):
        payload["override_status"] = source_group.get("status")
    else:
        payload["override_type"] = type(source_group).__name__
    return payload, tasks


def _invalid_source_override_file_group(
    group: str,
    hard: dict[str, Any],
    error: Exception,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tasks = hard[group].get("chrome_tasks", [])
    payload = blocked_group("invalid_source_override_file", [SOURCE_OVERRIDE_PATH], tasks)
    payload["error"] = str(error)
    return payload, tasks


def _source_group_with_tasks(
    group: str,
    hard: dict[str, Any],
    overrides: dict[str, Any],
    expected_codes: Optional[list[str]] = None,
    allow_override: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if group not in overrides or not allow_override:
        return hard[group], hard[group].get("chrome_tasks", [])

    source_group = overrides[group]
    if not isinstance(source_group, dict):
        return _invalid_source_override_group(group, source_group, hard, [group])

    status = source_group.get("status")
    if status == "PASS":
        missing = _missing_required_override_fields(group, source_group, expected_codes)
        if missing:
            return _invalid_source_override_group(group, source_group, hard, missing)
        return source_group, []

    if status != "BLOCK":
        return _invalid_source_override_group(group, source_group, hard, ["status"])

    tasks = source_group.get("chrome_tasks")
    if not isinstance(tasks, list) or not tasks:
        tasks = hard[group].get("chrome_tasks", [])
    return source_group, tasks


def _indicator_value(item: dict[str, Any], key: str) -> Optional[float]:
    direct = _as_number(item.get(key))
    if direct is not None:
        return direct
    indicators = item.get("indicators")
    if isinstance(indicators, dict):
        return _as_number(indicators.get(key))
    return None


def _close_value(item: dict[str, Any]) -> Optional[float]:
    direct = _as_number(item.get("close"))
    if direct is not None:
        return direct
    rows = item.get("rows")
    if isinstance(rows, list) and rows:
        latest = rows[-1]
        if isinstance(latest, dict):
            return _as_number(latest.get("close"))
    return None


def _derive_market_context(market: dict[str, Any], funds: dict[str, Any]) -> dict[str, Any]:
    payload = dict(market)
    if payload.get("status") != "PASS":
        return payload

    items = payload.get("items")
    index_items = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    above_ma10 = 0
    above_ma30 = 0
    below_ma30 = 0
    valid = 0
    for item in index_items:
        close = _close_value(item)
        ma10 = _indicator_value(item, "ma10")
        ma30 = _indicator_value(item, "ma30")
        if close is None or ma10 is None or ma30 is None:
            continue
        valid += 1
        if close >= ma10:
            above_ma10 += 1
        if close >= ma30:
            above_ma30 += 1
        if close < ma30:
            below_ma30 += 1

    fund_flow = 0.0
    fund_scale = 0.0
    fund_items = funds.get("items") if isinstance(funds, dict) else None
    if isinstance(fund_items, list):
        for item in fund_items:
            if isinstance(item, dict):
                value = _as_number(item.get("scale_change_billion"))
                if value is not None:
                    fund_flow += value
                scale = _as_number(item.get("scale_billion"))
                if scale is not None:
                    fund_scale += scale
    material_fund_flow = max(
        MIN_MATERIAL_FUND_FLOW_BILLION,
        fund_scale * MIN_MATERIAL_FUND_FLOW_RATIO,
    )

    if not payload.get("environment"):
        if valid < len(MARKET_INDEX_CODES):
            return payload
        if below_ma30 >= 2:
            payload["environment"] = "减量市场"
        elif above_ma10 >= 2 and above_ma30 >= 2 and fund_flow >= material_fund_flow:
            payload["environment"] = "增量市场"
        else:
            payload["environment"] = "存量市场"
    if not payload.get("stance"):
        if "减量" in str(payload.get("environment")):
            payload["stance"] = "防守"
        elif "增量" in str(payload.get("environment")):
            payload["stance"] = "进攻"
        else:
            payload["stance"] = "观察"
    return payload


def _derive_emotion_context(emotion: dict[str, Any]) -> dict[str, Any]:
    payload = dict(emotion)
    if payload.get("status") != "PASS" or payload.get("stage"):
        return payload

    limit_up_count = _as_number(payload.get("limit_up_count"))
    break_board_rate = _ratio_value(payload.get("break_board_rate"))
    height = _as_number(payload.get("height"))
    if limit_up_count is None or break_board_rate is None or height is None:
        return payload

    if break_board_rate >= 0.45 or limit_up_count < 25:
        payload["stage"] = "退潮"
    elif limit_up_count >= 80 and height >= 5 and break_board_rate < 0.35:
        payload["stage"] = "高潮"
    elif limit_up_count >= 50 and height >= 3:
        payload["stage"] = "发酵"
    else:
        payload["stage"] = "启动/修复"
    return payload


def collect_snapshot(workspace: Path, offline: bool = False) -> dict[str, Any]:
    workspace = Path(workspace).expanduser().resolve()
    state = collect_state_group(workspace)
    hard = collect_hard_source_groups(offline)

    market_default = collect_market_group(offline)
    stock_default = collect_stock_group(workspace, offline, state)
    stock_expected_codes = (
        _collect_codes(state.get("positions", []) + state.get("watchlist", []))
        if state.get("status") != "BLOCK"
        else []
    )
    kline_fallbacks = collect_kline_fallback_groups(market_default, stock_default)
    defaults: dict[str, Any] = {**hard, **kline_fallbacks}
    override_allowed = {
        group: offline or defaults[group].get("status") == "BLOCK"
        for group in ("funds", "sectors", "emotion", "market", "stocks")
    }

    overrides: dict[str, Any] = {}
    override_error: Optional[Exception] = None
    if any(override_allowed.values()):
        try:
            overrides = load_source_overrides(workspace)
        except ValueError as error:
            override_error = error

    if override_error is not None and override_allowed["funds"]:
        funds, funds_tasks = _invalid_source_override_file_group("funds", defaults, override_error)
    else:
        funds, funds_tasks = _source_group_with_tasks(
            "funds", defaults, overrides, allow_override=override_allowed["funds"]
        )
    if override_error is not None and override_allowed["sectors"]:
        sectors, sectors_tasks = _invalid_source_override_file_group("sectors", defaults, override_error)
    else:
        sectors, sectors_tasks = _source_group_with_tasks(
            "sectors", defaults, overrides, allow_override=override_allowed["sectors"]
        )
    if override_error is not None and override_allowed["emotion"]:
        emotion, emotion_tasks = _invalid_source_override_file_group("emotion", defaults, override_error)
    else:
        emotion, emotion_tasks = _source_group_with_tasks(
            "emotion", defaults, overrides, allow_override=override_allowed["emotion"]
        )
    if override_error is not None and override_allowed["market"]:
        market, market_tasks = _invalid_source_override_file_group("market", defaults, override_error)
    else:
        market, market_tasks = _source_group_with_tasks(
            "market",
            defaults,
            overrides,
            MARKET_INDEX_CODES,
            allow_override=override_allowed["market"],
        )
    if override_error is not None and override_allowed["stocks"]:
        stocks, stock_tasks = _invalid_source_override_file_group("stocks", defaults, override_error)
    else:
        stocks, stock_tasks = _source_group_with_tasks(
            "stocks",
            defaults,
            overrides,
            stock_expected_codes,
            allow_override=override_allowed["stocks"],
        )
    market = _derive_market_context(market, funds)
    emotion = _derive_emotion_context(emotion)

    sector_flow = fetch_sector_flow_python()
    margin = fetch_margin_group_python()
    northbound = fetch_northbound_flow_python()

    weekly_data: dict[str, Any] = {}
    if state.get("status") == "PASS" and not offline:
        positions = state.get("positions", [])
        for pos in positions:
            if not isinstance(pos, dict):
                continue
            code = str(pos.get("code") or "").strip()
            if not code:
                continue
            weekly_result = fetch_weekly_kline(code, weeks=60)
            if weekly_result.get("status") == "PASS":
                weekly_data[code] = weekly_result

    snapshot: dict[str, Any] = {
        "state": state,
        "market": market,
        "stocks": stocks,
        "funds": funds,
        "sectors": sectors,
        "emotion": emotion,
        "sector_flow": sector_flow,
        "margin": margin,
        "northbound": northbound,
        "weekly": weekly_data,
        "chrome_tasks": funds_tasks + sectors_tasks + emotion_tasks + market_tasks + stock_tasks,
        "collected_at": now_iso(),
    }
    snapshot["gate"] = data_gate(snapshot)
    return snapshot


def data_gate(snapshot: dict[str, Any]) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    warns: list[dict[str, Any]] = []

    for group in REQUIRED_GROUPS:
        item = snapshot.get(group)
        if not isinstance(item, dict):
            blocks.append({"group": group, "reason": "missing_group", "missing": [group]})
            continue

        status = item.get("status")
        if status is None:
            blocks.append({"group": group, "reason": "missing_status", "missing": ["status"]})
        elif status not in VALID_GROUP_STATUSES:
            blocks.append({"group": group, "reason": "invalid_status", "status": status})
        elif status == "BLOCK":
            block = {
                "group": group,
                "reason": item.get("reason", "blocked"),
                "missing": item.get("missing", []),
            }
            blocks.append(block)
        elif status == "WARN":
            warn = {
                "group": group,
                "reason": item.get("reason", "warning"),
                "missing": item.get("missing", []),
            }
            warns.append(warn)

    if blocks:
        return {"status": "BLOCK", "blocks": blocks, "warns": warns}
    if warns:
        return {"status": "WARN", "blocks": [], "warns": warns}
    return {"status": "PASS", "blocks": [], "warns": []}


def parse_closes(value: str) -> list[float]:
    closes = []
    for part in value.split(","):
        stripped = part.strip()
        if stripped:
            closes.append(float(stripped))
    return closes


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = JsonArgumentParser(description="l-stock market data helpers")
    subcommands = parser.add_subparsers(dest="command", required=True)

    calc_parser = subcommands.add_parser("calc-ma", help="calculate moving averages")
    calc_parser.add_argument("--closes", required=True, help="comma-separated close prices")

    gate_parser = subcommands.add_parser("gate", help="run required data gate")
    gate_parser.add_argument("--snapshot", required=True, help="path to snapshot JSON")

    kline_parser = subcommands.add_parser("fetch-kline", help="fetch Eastmoney daily K-line data")
    kline_parser.add_argument("--code", required=True, help="six-digit stock/fund code")
    kline_parser.add_argument("--days", type=int, default=120, help="number of recent rows to keep")

    collect_parser = subcommands.add_parser("collect", help="collect snapshot data")
    collect_parser.add_argument("--workspace", default=".", help="l-stock workspace")
    collect_parser.add_argument("--offline", action="store_true", help="skip network fetches")

    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
        if args.command == "calc-ma":
            payload = calc_ma(parse_closes(args.closes))
            exit_code = 0
        elif args.command == "gate":
            snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
            payload = data_gate(snapshot)
            exit_code = 2 if payload["status"] == "BLOCK" else 0
        elif args.command == "fetch-kline":
            payload = fetch_eastmoney_kline(args.code, args.days)
            exit_code = 0
        elif args.command == "collect":
            payload = collect_snapshot(Path(args.workspace), args.offline)
            exit_code = 0
        else:
            raise ValueError(f"Unknown command: {args.command}")
    except Exception as error:
        print(json.dumps({"status": "ERROR", "error": str(error)}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
