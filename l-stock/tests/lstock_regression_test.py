#!/usr/bin/env python3
import base64
import contextlib
import inspect
import importlib.util
import json
import tempfile
from http.client import RemoteDisconnected
from io import StringIO
from pathlib import Path
from unittest.mock import patch


SKILL_DIR = Path("/Users/bytedance/.codex/skills/l-stock")


def load_module(name: str, relative: str):
    path = SKILL_DIR / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lstock_data = load_module("lstock_data_regression", "scripts/lstock_data.py")
lstock_report = load_module("lstock_report_regression", "scripts/lstock_report.py")
lstock_cli = load_module("lstock_cli_regression", "scripts/lstock.py")


class FakeResponse:
    status = 200

    def __init__(self, payload: str):
        self.payload = payload.encode("utf-8")

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeCompletedProcess:
    def __init__(self, stdout: str, returncode: int = 0, stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def sina_jsonp(symbol: str, rows: int = 50) -> str:
    payload = [
        {
            "day": f"2026-04-{(index % 28) + 1:02d}",
            "open": str(index),
            "high": str(index + 0.5),
            "low": str(index - 0.5),
            "close": str(index),
            "volume": str(index * 1000),
        }
        for index in range(1, rows + 1)
    ]
    return f"var _{symbol}_240_({json.dumps(payload)});"


def sample_rows(count: int = 80, start: float = 10.0, step: float = 0.2):
    if isinstance(count, list):
        closes = [round(float(value), 2) for value in count]
    else:
        closes = [round(start + index * step, 2) for index in range(count)]
    rows = []
    for index, close in enumerate(closes):
        rows.append(
            {
                "date": f"2026-06-{(index % 28) + 1:02d}",
                "open": round(close - 0.1, 2),
                "close": close,
                "high": round(close + 0.4, 2),
                "low": round(close - 0.4, 2),
                "volume": 100000 + index * 1000,
                "amount": 0,
            }
        )
    return rows


def test_kline_falls_back_to_sina_when_eastmoney_disconnects():
    def fake_urlopen(request, timeout=0):
        url = request.full_url
        if "push2his.eastmoney.com" in url:
            raise RemoteDisconnected("Remote end closed connection without response")
        if "quotes.sina.cn" in url:
            return FakeResponse(sina_jsonp("sz000725"))
        raise AssertionError(url)

    with patch.object(lstock_data.urllib.request, "urlopen", side_effect=fake_urlopen):
        payload = lstock_data.fetch_eastmoney_kline("000725", days=50)

    assert payload["status"] == "PASS", payload
    assert payload["source"] == "sina_kline"
    assert payload["rows"][-1]["close"] == 50.0
    assert payload["indicators"]["ma40"] == 30.5


def test_jisilu_unit_fields_are_valid_fund_scale_fields():
    sample = {
        "rows": [
            {
                "cell": {
                    "fund_id": "159007",
                    "fund_nm": "养殖ETF华泰柏瑞",
                    "unit_total": "1.61",
                    "unit_incr": "-0.01",
                    "volume": "2092.71",
                }
            }
        ]
    }

    with patch.object(lstock_data, "_request_json", return_value=sample):
        payload = lstock_data.fetch_funds_group_python()

    assert payload["status"] == "PASS", payload
    assert payload["items"][0]["scale_billion"] == 1.61
    assert payload["items"][0]["scale_change_billion"] == -0.01
    assert payload["items"][0]["turnover"] == "2092.71万"


def test_emotion_uses_dated_limit_up_and_break_board_pools():
    def fake_request_json(url, **kwargs):
        assert "date=" in url
        if "getTopicZTPool" in url:
            return {
                "data": {
                    "tc": 96,
                    "pool": [
                        {"lbc": 5, "n": "江钨装备"},
                        {"lbc": 3, "n": "东方锆业"},
                    ],
                }
            }
        if "getTopicZBPool" in url:
            return {"data": {"tc": 50, "pool": []}}
        raise AssertionError(url)

    with patch.object(lstock_data, "_recent_china_dates", return_value=["20260623"]):
        with patch.object(lstock_data, "_request_json", side_effect=fake_request_json):
            payload = lstock_data.fetch_emotion_group_python()

    assert payload["status"] == "PASS", payload
    assert payload["limit_up_count"] == 96
    assert payload["break_board_rate"] == 0.3425
    assert payload["height"] == 5
    assert payload["trade_date"] == "20260623"
    assert "江钨装备" in payload["leader_performance"]


def test_emotion_falls_back_to_recent_non_empty_trade_date():
    calls = []

    def fake_request_json(url, **kwargs):
        calls.append(url)
        if "getTopicZTPool" in url and "date=20260623" in url:
            return {"data": {"tc": 0, "pool": []}}
        if "getTopicZTPool" in url and "date=20260622" in url:
            return {"data": {"tc": 12, "pool": [{"lbc": 2, "n": "测试龙头"}]}}
        if "getTopicZBPool" in url and "date=20260622" in url:
            return {"data": {"tc": 3, "pool": []}}
        raise AssertionError(url)

    with patch.object(lstock_data, "_recent_china_dates", return_value=["20260623", "20260622"]):
        with patch.object(lstock_data, "_request_json", side_effect=fake_request_json):
            payload = lstock_data.fetch_emotion_group_python()

    assert payload["status"] == "PASS", payload
    assert payload["limit_up_count"] == 12
    assert payload["break_board_rate"] == 0.2
    assert payload["trade_date"] == "20260622"
    assert any("date=20260622" in url for url in calls)


def test_sector_flow_retries_http_when_https_disconnects():
    def fake_request_json(url, **kwargs):
        if url.startswith("https://"):
            raise RemoteDisconnected("Remote end closed connection without response")
        assert url.startswith("http://")
        return {
            "data": {
                "diff": [
                    {
                        "f14": "银行",
                        "f3": 1.56,
                        "f62": 2868747264.0,
                        "f66": 1723277568.0,
                    }
                ]
            }
        }

    with patch.object(lstock_data, "_request_json", side_effect=fake_request_json):
        payload = lstock_data.fetch_sectors_group_python()

    assert payload["status"] == "PASS", payload
    assert payload["items"][0]["name"] == "银行"
    assert payload["items"][0]["main_net_inflow"] == "28.69亿"


def test_watchlist_actions_skip_current_positions():
    snapshot = {
        "state": {
            "positions": [{"code": "300782", "name": "卓胜微", "price": 113.92}],
            "watchlist": [
                {"code": "300782", "name": "卓胜微", "price": 113.92},
                {"code": "000725", "name": "京东方A", "price": 6.77},
            ],
            "preferences": {"risk": {"minimum_odds_ratio": 2.0}},
        },
        "stocks": {"items": []},
        "market": {"environment": "存量市场"},
        "emotion": {"stage": "高潮"},
    }

    position_actions, watch_actions = lstock_report._collect_actions(snapshot)

    assert [action["stock"] for action in position_actions] == ["卓胜微（300782）"]
    assert [action["stock"] for action in watch_actions] == ["京东方A（000725）"]


def test_report_evidence_compacts_kline_rows():
    snapshot = {
        "gate": {"status": "PASS", "blocks": [], "warns": []},
        "market": {
            "status": "PASS",
            "source": "sina_kline",
            "environment": "存量市场",
            "stance": "观察",
            "items": [
                {
                    "code": "000300",
                    "name": "沪深300",
                    "source": "sina_kline",
                    "rows": [{"close": 1.0}, {"close": 2.0}],
                    "indicators": {"ma20": 1.5, "ma40": 1.2},
                    "fallback_from": {"source": "eastmoney_kline", "error": "disconnect"},
                }
            ],
        },
        "emotion": {
            "status": "PASS",
            "source": "python:eastmoney_zt_pool",
            "stage": "高潮",
            "limit_up_count": 96,
            "break_board_rate": 0.3425,
            "height": 5,
            "leader_performance": "连板高度 5",
        },
        "state": {
            "positions": [],
            "watchlist": [],
            "preferences": {"risk": {"reserve_cash_ratio": 0.0}},
        },
        "stocks": {"items": []},
    }

    report = lstock_report.render(snapshot)

    assert "market JSON（摘要）" in report
    assert '"rows"' not in report
    assert '"error"' not in report
    assert '"fallback_from": "eastmoney_kline"' in report
    assert '"close": 2.0' in report
    assert '"ma20": 1.5' in report


def test_watchlist_missing_target_or_stop_stays_technical_tracking_without_odds_noise():
    action = lstock_report.watch_action({"code": "000636", "name": "风华高科", "price": 70.21})

    assert action["bucket"] == "观察等待"
    assert action["action"] == "技术跟踪"
    assert "技术跟踪" in action["text"]
    assert "0:1" not in action["text"]
    assert "赔率" not in action["text"]
    assert "无法计算赔率" not in action["text"]
    assert "缺少目标价" not in action["text"]
    assert "缺少止损价" not in action["text"]
    assert "目标价/止损价" not in action["text"]
    assert "补齐计划" not in action["text"]
    assert "禁止买入" not in action["text"]


def test_watchlist_web_action_is_technical_tracking_without_odds_noise():
    item = {
        "code": "000636",
        "name": "风华高科",
        "price": 70.21,
        "rows": sample_rows([65, 66, 68, 70, 72, 71, 70, 69, 70, 71, 72, 73, 72, 71, 70, 71, 72, 73, 74, 73, 72]),
        "indicators": {"ma20": 70.1, "ma40": 68.5},
    }

    action = lstock_report._watchlist_web_action(item)

    assert action["bucket"] == "观察等待"
    assert action["action"] == "技术跟踪"
    assert "接近支撑" in action["text"] or "突破压力" in action["text"] or "趋势" in action["text"]
    assert "0:1" not in action["text"]
    assert "赔率" not in action["text"]
    assert "补齐计划" not in action["text"]
    assert "缺少目标价" not in action["text"]
    assert "缺少止损价" not in action["text"]


def test_watchlist_web_action_still_appears_in_legacy_action_groups_html():
    item = {
        "code": "000636",
        "name": "风华高科",
        "price": 70.21,
        "rows": sample_rows([65, 66, 68, 70, 72, 71, 70, 69, 70, 71, 72, 73, 72, 71, 70, 71, 72, 73, 74, 73, 72]),
        "indicators": {"ma20": 70.1, "ma40": 68.5},
    }

    action = lstock_report._watchlist_web_action(item)
    html = lstock_report._action_groups_html([], [action])

    assert "技术跟踪" in html
    assert "风华高科" in html


def test_trend_status_does_not_mark_price_above_ma40_as_broken():
    item = {
        "code": "300782",
        "name": "卓胜微",
        "price": 113.92,
        "indicators": {"ma20": 103.57, "ma40": 109.6},
    }

    text = lstock_report._trend_status_text(item)

    assert "跌破 MA40" not in text
    assert "修复" in text


def test_technical_support_does_not_use_hard_stop_as_support():
    rows = sample_rows(count=20, start=100, step=1)
    item = {
        "code": "600176",
        "name": "中国巨石",
        "price": 120,
        "stop": 10,
        "rows": rows,
        "indicators": {"ma20": 110, "ma40": 105},
    }

    support, _pressure = lstock_report._recent_support_pressure(item)

    assert support is not None
    assert support > 10


def test_ohlcv_rows_skip_incomplete_candles_without_fabricating_prices():
    rows = [
        {"date": "2026-06-01", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000},
        {"date": "2026-06-02", "close": 10.8, "volume": 1200},
        {"date": "2026-06-03", "open": 10.8, "high": 12, "low": 10.6, "close": 11.5, "volume": 1400},
    ]

    candles = lstock_report._ohlcv_rows({"rows": rows})

    assert len(candles) == 2
    assert candles[0]["open"] == 10.0
    assert candles[1]["date"] == "2026-06-03"
    assert all("high" in candle and "low" in candle for candle in candles)


def test_support_resistance_levels_use_swing_zones_and_keep_stop_separate():
    rows = sample_rows(count=70, start=90, step=0.4)
    rows[-8]["low"] = 105
    rows[-5]["low"] = 105.4
    rows[-3]["high"] = 123
    rows[-1]["high"] = 123.3
    item = {
        "code": "301205",
        "name": "联特科技",
        "stop": 80,
        "rows": rows,
        "indicators": {"ma20": 112, "ma40": 106},
    }

    levels = lstock_report._support_resistance_levels(item)

    assert levels["support"]["value"] != 80
    assert levels["hard_stop"]["value"] == 80
    assert levels["support"]["low"] < levels["support"]["high"]
    assert levels["resistance"]["low"] < levels["resistance"]["high"]
    assert levels["support"]["confidence"] in {"medium", "high"}
    assert levels["resistance"]["confidence"] in {"medium", "high"}


def test_price_level_ladder_uses_chinese_display_labels_and_source_notes():
    rows = sample_rows([18, 19, 20, 22, 24, 26, 25, 23, 21, 22, 24, 26, 28, 27, 25, 24, 23, 24, 25, 26, 25, 24, 23, 24, 25, 26])
    item = {
        "code": "301205",
        "name": "联特科技",
        "price": 25.5,
        "rows": rows,
        "indicators": {"ma20": 24.2, "ma40": 23.7},
        "position": {"stop_price": 21.67},
    }

    ladder = lstock_report._price_level_ladder(item)
    labels = [level["display_label"] for level in ladder]
    source_labels = [level["source_label"] for level in ladder]

    assert "上方压力" in labels
    assert "当前价" in labels
    assert "下方支撑" in labels
    assert "硬止损" in labels
    assert "最新收盘" in source_labels
    assert any("MA20 动态位" == source for source in source_labels)
    assert any(source in {"前高密集区", "前低密集区"} for source in source_labels)


def test_price_level_ladder_keeps_hard_stop_separate_from_technical_support():
    rows = sample_rows([100, 101, 102, 104, 106, 108, 107, 105, 103, 104, 106, 108, 110, 109, 107, 106, 105, 106, 107, 108, 107, 106, 105, 106, 107, 108])
    item = {
        "code": "603688",
        "name": "石英股份",
        "price": 108,
        "rows": rows,
        "indicators": {"ma20": 106.4, "ma40": 104.8},
        "position": {"stop_price": 91.8},
    }

    ladder = lstock_report._price_level_ladder(item)
    technical_supports = [level for level in ladder if level["display_label"] == "下方支撑"]
    hard_stops = [level for level in ladder if level["display_label"] == "硬止损"]

    assert technical_supports
    assert hard_stops
    assert all(level["source"] != "hard_stop" for level in technical_supports)
    assert hard_stops[0]["source"] == "hard_stop"
    assert hard_stops[0]["source_label"] == "账户纪律"


def test_price_level_ladder_marks_ma_levels_as_dynamic_not_horizontal_zones():
    rows = sample_rows([40, 41, 42, 44, 46, 48, 47, 45, 43, 44, 46, 48, 50, 49, 47, 46, 45, 46, 47, 48, 47, 46, 45, 46, 47, 48])
    item = {
        "code": "600309",
        "name": "万华化学",
        "price": 48,
        "rows": rows,
        "indicators": {"ma20": 46.4, "ma40": 44.8},
    }

    ladder = lstock_report._price_level_ladder(item)
    ma_levels = [level for level in ladder if level["source"].startswith("ma")]

    assert ma_levels
    assert all(level["is_dynamic"] for level in ma_levels)
    assert all("band_low" not in level and "band_high" not in level for level in ma_levels)


def test_support_pressure_text_uses_next_day_chinese_level_names():
    item = {
        "code": "600309",
        "name": "万华化学",
        "price": 72.8,
        "rows": sample_rows([68, 69, 70, 72, 74, 73, 72, 71, 72, 73, 74, 75, 74, 73, 72, 73, 74, 75, 76, 75, 74]),
        "indicators": {"ma20": 72.3, "ma40": 78.11},
        "position": {"stop_price": 61.88},
    }

    text = lstock_report._support_pressure_text(item)

    assert "下一交易日价位" in text
    assert "上方压力" in text
    assert "当前价" in text
    assert "下方支撑" in text
    assert "硬止损" in text
    assert "R1" not in text
    assert "S1" not in text
    assert "STOP" not in text


def test_support_pressure_text_prefers_nearest_side_levels_over_far_ma():
    rows = sample_rows([98, 99, 100, 101, 102, 103, 102, 101, 100, 101, 102, 103, 104, 103, 102, 101, 100, 101, 102, 103, 102, 101, 100, 101, 102, 103])
    rows[-3]["high"] = 106
    rows[-2]["high"] = 106.2
    rows[-1]["close"] = 103
    item = {
        "code": "600309",
        "name": "万华化学",
        "price": 103,
        "rows": rows,
        "indicators": {"ma20": 101.8, "ma40": 130.0},
        "position": {"stop_price": 87.55},
    }

    text = lstock_report._support_pressure_text(item)

    assert "上方压力 106.1" in text
    assert "上方压力 130" not in text
    assert "下方支撑 102.02" in text


def test_support_pressure_text_omits_stale_below_price_target_as_pressure():
    item = {
        "code": "600309",
        "name": "万华化学",
        "price": 100,
        "target": 90,
        "indicators": {"ma20": 80},
    }

    text = lstock_report._support_pressure_text(item)

    assert "当前价 100" in text
    assert "下方支撑 80" in text
    assert "上方压力" not in text
    assert "目标价，位于现价下方" not in text


def test_kline_chart_png_contains_candlestick_visual_elements_and_metadata():
    rows = sample_rows(count=80, start=30, step=0.5)
    item = {
        "code": "301205",
        "name": "联特科技",
        "stop": 25,
        "rows": rows,
        "indicators": {"ma20": 62, "ma40": 55},
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        report_path = Path(tmpdir) / "report.md"
        chart_path = lstock_report._write_kline_chart(item, report_path)
        meta = lstock_report._chart_meta(item)

        assert chart_path is not None
        assert chart_path.is_file()
        assert chart_path.stat().st_size > 50000
        assert meta["style"] == "candlestick"
        assert meta["candle_count"] >= 60
        assert meta["has_volume"] is True
        assert meta["has_ma5"] is True
        assert meta["has_ma20"] is True
        assert meta["has_ma40"] is True
        assert meta["support"]["value"] is not None
        assert meta["hard_stop"]["value"] == 25
        assert meta["price_ladder"]
        assert {level["display_label"] for level in meta["price_ladder"]} >= {"上方压力", "当前价", "下方支撑", "硬止损"}


def test_chart_meta_ma_flags_match_rendered_ma_lines_for_short_candle_sets():
    item = {
        "code": "301205",
        "name": "联特科技",
        "rows": sample_rows(count=12, start=30, step=0.5),
        "indicators": {"ma20": 32, "ma40": 31},
    }

    meta = lstock_report._chart_meta(item)

    assert meta["style"] == "candlestick"
    assert meta["has_ma5"] is True
    assert meta["has_ma20"] is False
    assert meta["has_ma40"] is False


def test_kline_chart_filename_sanitizes_hostile_codes_inside_asset_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        report_path = Path(tmpdir) / "report.md"
        asset_dir = Path(tmpdir) / "report-assets"

        with patch.object(lstock_report, "_kline_chart_png_bytes", return_value=b"png"):
            traversal_path = lstock_report._write_kline_chart({"code": "../bad/300001"}, report_path)
            script_path = lstock_report._write_kline_chart({"code": '"><script>'}, report_path)

        assert traversal_path == asset_dir / "bad300001.png"
        assert script_path == asset_dir / "script.png"
        assert traversal_path.is_file()
        assert script_path.is_file()
        assert traversal_path.parent == asset_dir
        assert script_path.parent == asset_dir
        assert not (Path(tmpdir) / "bad").exists()


def test_kline_chart_bytes_and_data_uri_are_reusable_for_html():
    rows = sample_rows(count=80, start=30, step=0.5)
    item = {
        "code": "301205",
        "name": "联特科技",
        "stop": 25,
        "rows": rows,
        "indicators": {"ma20": 62, "ma40": 55},
    }

    png_bytes = lstock_report._kline_chart_png_bytes(item)
    data_uri = lstock_report._kline_chart_data_uri(item)

    assert png_bytes is not None
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(png_bytes) > 50000
    assert data_uri is not None
    assert data_uri.startswith("data:image/png;base64,")
    decoded_data_uri = base64.b64decode(data_uri.removeprefix("data:image/png;base64,"), validate=True)
    assert decoded_data_uri.startswith(b"\x89PNG\r\n\x1a\n")
    assert "report-assets" not in data_uri


def test_chart_note_wraps_long_chinese_lines_for_side_panel():
    wrapped = lstock_report._wrap_chart_note_lines(
        ["现价 323.49 位于 MA20 321.74 和 MA40 295.1 上方，短中期结构偏强。"],
        width=18,
    )

    assert "\n" in wrapped
    assert "现价 323.49" in wrapped


def test_price_rail_label_layout_offsets_close_labels_without_changing_anchor_values():
    levels = [
        {"display_label": "上方压力", "value": 74.66, "source_label": "前高密集区", "kind": "resistance"},
        {"display_label": "当前价", "value": 72.8, "source_label": "最新收盘", "kind": "price"},
        {"display_label": "下方支撑", "value": 72.45, "source_label": "MA20 动态位", "kind": "support"},
        {"display_label": "硬止损", "value": 61.88, "source_label": "账户纪律", "kind": "stop"},
    ]

    layout = lstock_report._layout_price_rail_labels(levels, y_min=60, y_max=76, min_gap_ratio=0.08)

    assert [row["value"] for row in layout] == [74.66, 72.8, 72.45, 61.88]
    assert all("label_y" in row for row in layout)
    assert abs(layout[1]["label_y"] - layout[2]["label_y"]) >= (76 - 60) * 0.08
    assert layout[1]["label_y"] != layout[1]["value"] or layout[2]["label_y"] != layout[2]["value"]


def test_hard_stop_chart_note_is_short_and_separate():
    note = lstock_report._level_note({"value": 293.77, "source": "hard_stop", "confidence": "hard"}, "硬止损")

    assert note == "硬止损：293.77"


def report_snapshot_fixture():
    rows = sample_rows()
    return {
        "gate": {"status": "PASS", "blocks": [], "warns": []},
        "market": {
            "status": "PASS",
            "source": "sina_kline",
            "environment": "存量市场",
            "stance": "观察",
            "items": [
                {"code": "000300", "name": "沪深300", "close": 4919.386, "ma20": 4873.6695, "ma40": 4864.6181},
                {"code": "000905", "name": "中证500", "close": 8688.592, "ma20": 8389.7913, "ma40": 8470.0719},
                {"code": "399006", "name": "创业板指", "close": 4192.194, "ma20": 4040.2956, "ma40": 3938.201},
            ],
        },
        "funds": {
            "status": "PASS",
            "items": [
                {"code": "159001", "name": "样本ETF", "scale_change_billion": 1.2, "scale_billion": 50, "turnover": "1000万"}
            ],
        },
        "sectors": {
            "status": "PASS",
            "items": [
                {"name": "电子", "change_pct": 2.3, "main_net_inflow": "12.30亿", "super_large_net_inflow": "5.20亿"},
                {"name": "银行", "change_pct": 1.1, "main_net_inflow": "8.10亿", "super_large_net_inflow": "3.00亿"},
            ],
        },
        "emotion": {
            "status": "PASS",
            "source": "python:eastmoney_zt_pool",
            "stage": "高潮",
            "trade_date": "20260623",
            "limit_up_count": 96,
            "break_board_rate": 0.3425,
            "height": 5,
            "leader_performance": "连板高度 5，代表 江钨装备",
        },
        "state": {
            "positions": [
                {"code": "301205", "name": "联特科技", "quantity": 300, "cost": 345.614, "stop": 293.77}
            ],
            "watchlist": [
                {"code": "000636", "name": "风华高科", "price": 70.21}
            ],
            "preferences": {"risk": {"reserve_cash_ratio": 0.0, "minimum_odds_ratio": 2.0}},
        },
        "stocks": {
            "status": "PASS",
            "items": [
                {"code": "301205", "name": "联特科技", "source": "sina_kline", "rows": rows, "indicators": {"ma20": 22.9, "ma40": 20.9}},
                {"code": "000636", "name": "风华高科", "source": "sina_kline", "rows": rows, "indicators": {"ma20": 22.9, "ma40": 20.9}},
            ],
        },
    }


def test_enriched_report_has_market_thesis_stock_playbooks_and_chart_assets():
    snapshot = report_snapshot_fixture()

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "report.md"
        payload = lstock_report.render_markdown_to_file(snapshot, output_path, include_images=True)
        report = output_path.read_text(encoding="utf-8")

        assert payload["format"] == "markdown"
        assert payload["chart_count"] == 2
        assert payload.get("chart_style") == "candlestick"
        assert (Path(tmpdir) / "report-assets" / "301205.png").is_file()
        assert (Path(tmpdir) / "report-assets" / "000636.png").is_file()

    assert "## 市场证据链" in report
    assert "3/3 个核心指数站上 MA20" in report
    assert "涨停 96 家" in report
    assert "电子" in report
    assert "本次结论：" not in report
    assert "第一页" not in report
    assert "## 交易摘要" in report
    assert "### 今日结论" in report
    assert "### 必备交易操作" in report
    assert "### 可选交易操作" in report
    assert "### 持仓与观察" in report
    assert "## 持仓诊断" in report
    assert "### 联特科技（301205）" in report
    assert "<table" not in report
    assert 'width="720"' not in report
    assert "![联特科技 K线图](report-assets/301205.png)" in report
    assert "支撑" in report
    assert "压力" in report
    assert "远期剧本" in report
    assert "综合推断：推断：" not in report
    assert "## 关注池剧本" in report
    assert "### 风华高科（000636）" in report


def test_markdown_final_report_keeps_watchlist_as_technical_tracking_without_forbidden_terms():
    report = lstock_report.render(report_snapshot_fixture())
    watch_start = report.index("## 关注池剧本")
    watch_report = report[watch_start:]

    assert "技术跟踪" in watch_report
    for term in ("0:1", "赔率", "无法计算赔率", "缺少目标价", "缺少止损价", "目标价/止损价", "目标/止损/技术信号", "补齐计划"):
        assert term not in report


def test_markdown_action_table_uses_watchlist_technical_tracking_fields():
    action = lstock_report.watch_action({"code": "000636", "name": "风华高科", "price": 70.21})
    lines = []

    lstock_report._append_action_table(lines, [], [action])
    table = "\n".join(lines)

    assert "支撑/压力/均线" in table
    assert "只做技术跟踪" in table
    assert "目标/止损/技术信号" not in table
    assert "保留现金" not in table


def test_watchlist_with_stop_target_filters_trade_plan_levels_from_final_reports():
    snapshot = json.loads(json.dumps(report_snapshot_fixture(), ensure_ascii=False))
    snapshot["state"]["watchlist"][0]["stop"] = 60.0
    snapshot["state"]["watchlist"][0]["target"] = 88.0
    forbidden_terms = ("硬止损", "止损", "账户纪律", "stop", "目标价", "目标/止损/技术信号", "赔率", "补齐计划")

    markdown = lstock_report.render(snapshot)
    markdown_start = markdown.index("## 关注池剧本")
    markdown_end = markdown.index("## 诊断证据")
    watch_markdown = markdown[markdown_start:markdown_end]

    assert "技术跟踪" in watch_markdown
    assert "上方压力" in watch_markdown
    assert "下方支撑" in watch_markdown
    for term in forbidden_terms:
        assert term not in watch_markdown

    chart_calls = []

    def fake_chart(item, *, include_trade_plan_levels=True):
        chart_calls.append((str(item.get("code")), include_trade_plan_levels))
        return b"png"

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "report.html"
        with patch.object(lstock_report, "_kline_chart_png_bytes", side_effect=fake_chart):
            lstock_report.render_html_to_file(snapshot, output_path)
        html = output_path.read_text(encoding="utf-8")

    watch_start = html.index('id="watchlist-tracking"')
    watch_end = html.index('id="data-appendix"')
    watch_html = html[watch_start:watch_end]

    assert ("301205", True) in chart_calls
    assert ("000636", False) in chart_calls
    assert "技术跟踪" in watch_html
    assert "上方压力" in watch_html
    assert "下方支撑" in watch_html
    for term in forbidden_terms:
        assert term not in watch_html


def test_normalized_duplicate_codes_do_not_cross_identity_chart_resources():
    snapshot = json.loads(json.dumps(report_snapshot_fixture(), ensure_ascii=False))
    rows = sample_rows()
    snapshot["state"]["positions"] = [{"code": "000636 ", "name": "风华高科", "quantity": 100, "stop": 20.0}]
    snapshot["state"]["watchlist"] = [
        {"code": "000636", "name": "风华高科", "stop": 18.0},
        {"code": "000777", "name": "中核科技", "stop": 15.0},
    ]
    snapshot["stocks"]["items"] = [
        {"code": "000636", "name": "风华高科", "source": "sina_kline", "rows": rows, "indicators": {"ma20": 22.9, "ma40": 20.9}},
        {"code": "000777", "name": "中核科技", "source": "sina_kline", "rows": rows, "indicators": {"ma20": 22.9, "ma40": 20.9}},
    ]
    chart_calls = []

    def fake_chart(item, *, include_trade_plan_levels=True):
        chart_calls.append((_code := str(item.get("code")), include_trade_plan_levels))
        return f"png-{_code}-{include_trade_plan_levels}".encode("utf-8")

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "report.html"
        with patch.object(lstock_report, "_kline_chart_png_bytes", side_effect=fake_chart):
            lstock_report.render_html_to_file(snapshot, output_path)
        html = output_path.read_text(encoding="utf-8")

    assert ("000636 ", True) in chart_calls
    assert ("000636", False) not in chart_calls
    assert ("000777", False) in chart_calls

    position_start = html.index('id="positions"')
    watch_start = html.index('id="watchlist-tracking"')
    appendix_start = html.index('id="data-appendix"')
    position_html = html[position_start:watch_start]
    watch_html = html[watch_start:appendix_start]

    assert "风华高科（000636）" in position_html
    assert "硬止损" in position_html
    assert "账户纪律" in position_html
    assert "风华高科" not in watch_html
    assert "中核科技" in watch_html
    assert "硬止损" not in watch_html
    assert "账户纪律" not in watch_html


def test_below_price_target_is_not_rendered_as_upper_pressure_in_position_views():
    item = {
        "code": "301205",
        "name": "联特科技",
        "target": 23.17,
        "stop": 18.42,
        "rows": sample_rows(count=80, start=30, step=0.5),
        "indicators": {"ma20": 62, "ma40": 55},
    }

    text = lstock_report._support_pressure_text(item)
    table = lstock_report._price_level_table_html(item)
    card = lstock_report._stock_card_html(item, lstock_report.position_action(item), "position", 2.0, None)

    assert "23.17" not in text
    assert "23.17" not in table
    assert "23.17" not in card
    assert "目标价" not in text
    assert "目标价" not in table
    assert "目标价" not in card

    rows_without_above_pressure = [
        {"date": f"2026-06-{(index % 28) + 1:02d}", "open": 89.0, "close": 90.0, "high": 91.0, "low": 88.0, "volume": 1000, "amount": 0}
        for index in range(60)
    ]
    stale_target_item = {
        "code": "301205",
        "name": "联特科技",
        "close": 100.0,
        "target": 90.0,
        "stop": 80.0,
        "rows": rows_without_above_pressure,
        "indicators": {"ma20": 95.0, "ma40": 92.0},
    }

    chart_levels = lstock_report._chart_meta(stale_target_item)["price_ladder"]

    assert all(level.get("source") != "target" for level in chart_levels)
    assert all(level.get("display_label") != "上方压力" for level in chart_levels)
    assert all(level.get("value") != 90.0 for level in chart_levels if level.get("kind") == "resistance")


def test_markdown_image_mode_escapes_hostile_stock_identity():
    snapshot = json.loads(json.dumps(report_snapshot_fixture(), ensure_ascii=False))
    hostile_name = "<script>alert(1)</script> 坏]名\n# 注入[图]\\尾"
    hostile_code = "301205]x"
    snapshot["state"]["positions"][0]["name"] = hostile_name
    snapshot["state"]["positions"][0]["code"] = hostile_code
    snapshot["stocks"]["items"][0]["name"] = hostile_name
    snapshot["stocks"]["items"][0]["code"] = hostile_code

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "report.md"
        lstock_report.render_markdown_to_file(snapshot, output_path, include_images=True)
        report = output_path.read_text(encoding="utf-8")

    assert "### &lt;script&gt;alert\\(1\\)&lt;/script&gt; 坏\\]名 \\# 注入\\[图\\]\\\\尾（301205\\]x）" in report
    assert "![&lt;script&gt;alert\\(1\\)&lt;/script&gt; 坏\\]名 \\# 注入\\[图\\]\\\\尾 K线图]" in report
    assert "<script>" not in report
    assert "![坏]名" not in report
    assert "\n# 注入[图]" not in report


def test_markdown_export_is_clean_by_default_and_writes_to_requested_path():
    snapshot = report_snapshot_fixture()
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "output" / "report.md"
        payload = lstock_report.render_markdown_to_file(snapshot, output_path)
        markdown = output_path.read_text(encoding="utf-8")

        assert payload["format"] == "markdown"
        assert payload["chart_count"] == 0
        assert output_path.is_file()
        assert not (Path(tmpdir) / "output" / "report-assets").exists()
        assert "<table" not in markdown
        assert "<img" not in markdown
        assert "## 交易摘要" in markdown
        assert "## 持仓诊断" in markdown


def test_html_report_is_primary_visual_layout_with_embedded_assets():
    snapshot = report_snapshot_fixture()
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "report.html"
        payload = lstock_report.render_html_to_file(snapshot, output_path)
        html = output_path.read_text(encoding="utf-8")

        assert payload["format"] == "html"
        assert payload["report"] == str(output_path)
        assert payload["chart_count"] == 2
        assert "<!doctype html>" in html.lower()
        assert 'class="app-shell"' in html
        assert 'class="side-nav"' in html
        assert 'class="kpi-grid' in html
        assert 'class="stock-card"' in html
        assert 'class="stock-card-header"' in html
        assert 'class="stock-card-layout"' in html
        assert 'class="stock-insight-panel"' in html
        assert 'class="compact-detail compact-primary"' in html
        assert 'class="condition-list"' in html
        assert 'class="playbook-details"' in html
        assert 'class="chart-zoom-button"' in html
        assert 'data:image/png;base64,' in html
        assert 'src="report-assets/' not in html
        assert "@media print" in html
        assert "导出 PDF" in html
        assert "今日剧本" in html
        assert "市场温度计" in html
        assert "行动矩阵" in html
        assert "持仓诊断" in html
        assert "关注池技术跟踪" in html
        assert "数据附录" in html
        assert "执行分组" not in html
        assert "个股动作表" not in html
        assert "诊断证据" not in html
        assert "0:1" not in html
        assert "无法计算赔率" not in html
        assert "缺少目标价" not in html
        assert "缺少止损价" not in html
        assert "补齐计划" not in html
        assert "结构说明" not in html
        assert "图中右侧价位轨道使用中文标签" in html
        assert 'id="today-script"' in html
        assert 'id="market-thermometer"' in html
        assert 'id="action-matrix"' in html
        assert 'id="positions"' in html
        assert 'id="watchlist-tracking"' in html
        assert 'id="data-appendix"' in html
        content_html = html[html.index('<div class="content">'):]
        section_markers = [
            '<section class="report-section today-script" id="today-script">',
            '<section class="report-section market-thermometer" id="market-thermometer">',
            '<section class="report-section action-matrix" id="action-matrix">',
            '<details class="report-section collapsible" id="positions" open>',
            '<details class="report-section collapsible" id="watchlist-tracking">',
            '<details class="report-section collapsible data-appendix" id="data-appendix">',
        ]
        assert [content_html.index(marker) for marker in section_markers] == sorted(
            content_html.index(marker) for marker in section_markers
        )
        assert not (Path(tmpdir) / "report-assets").exists()


def test_html_report_includes_chart_lightbox_markup_and_behaviour():
    snapshot = report_snapshot_fixture()
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "report.html"
        lstock_report.render_html_to_file(snapshot, output_path)
        html = output_path.read_text(encoding="utf-8")

    assert 'class="chart-lightbox" id="chart-lightbox"' in html
    assert 'onclick="if (event.target === this) closeChartLightbox()"' in html
    assert 'id="chart-lightbox-image"' in html
    assert 'class="chart-lightbox-close"' in html
    assert "openChartLightbox" in html
    assert "closeChartLightbox" in html
    assert 'event.key === "Escape"' in html
    assert 'document.body.classList.add("lightbox-open")' in html
    assert 'document.body.classList.remove("lightbox-open")' in html

    data_block_html = lstock_report.render_data_block_html({"gate": {"status": "BLOCK", "blocks": []}})
    assert 'class="chart-lightbox" id="chart-lightbox"' not in data_block_html


def test_kline_png_source_css_and_js_keep_explanation_out_of_chart():
    source = inspect.getsource(lstock_report)
    start = source.index("def _kline_chart_png_bytes")
    end = source.index("def _safe_chart_code", start)
    kline_source = source[start:end]

    assert "结构说明" not in kline_source
    assert ".chart-note" in lstock_report.HTML_REPORT_CSS
    assert "结构说明" not in lstock_report.HTML_REPORT_CSS
    assert "结构说明" not in lstock_report.HTML_REPORT_JS


def test_stock_card_playbook_details_are_folded_but_expand_for_print_and_pdf():
    snapshot = report_snapshot_fixture()
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "report.html"
        lstock_report.render_html_to_file(snapshot, output_path)
        html = output_path.read_text(encoding="utf-8")

    assert '<details class="playbook-details">' in html
    assert '<details class="playbook-details" open>' not in html
    assert "details.playbook-details:not([open])" in lstock_report.HTML_REPORT_CSS
    assert "openPlaybooksForExport" in lstock_report.HTML_REPORT_JS
    assert "details.playbook-details" in lstock_report.HTML_REPORT_JS
    assert "openPlaybooksForExport();" in lstock_report.HTML_REPORT_JS


def test_html_report_uses_collapsible_position_watchlist_and_appendix_sections():
    snapshot = report_snapshot_fixture()
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "report.html"
        lstock_report.render_html_to_file(snapshot, output_path)
        html = output_path.read_text(encoding="utf-8")

    assert '<details class="report-section collapsible" id="positions" open>' in html
    assert '<details class="report-section collapsible" id="watchlist-tracking">' in html
    assert '<details class="report-section collapsible data-appendix" id="data-appendix">' in html
    assert "1 只 · 默认展开" in html
    assert "1 只 · 默认收起" in html
    assert "持仓图卡" not in html
    assert "关注池图卡" not in html


def test_watchlist_tracking_cards_render_kline_charts_like_position_cards():
    snapshot = report_snapshot_fixture()
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "report.html"
        payload = lstock_report.render_html_to_file(snapshot, output_path)
        html = output_path.read_text(encoding="utf-8")

    assert payload["chart_count"] == 2
    assert html.count('class="stock-card"') >= 2
    assert html.count("data:image/png;base64,") >= 2
    watch_start = html.index('id="watchlist-tracking"')
    watch_end = html.index('id="data-appendix"')
    watch_html = html[watch_start:watch_end]
    assert "关注池技术跟踪" in watch_html
    assert "技术跟踪" in watch_html
    assert "level-table" in watch_html
    assert "补齐计划" not in watch_html
    assert "无法计算赔率" not in watch_html
    assert "缺少目标价" not in watch_html
    assert "缺少止损价" not in watch_html
    assert "目标/止损/技术信号" not in watch_html


def test_html_report_css_contains_redesign_and_print_guards():
    css = lstock_report.HTML_REPORT_CSS

    assert ".today-script" in css
    assert ".market-thermometer" in css
    assert ".action-matrix" in css
    assert ".collapsible" in css
    assert ".stock-card-layout" in css
    assert "grid-template-columns: minmax(560px, 1.9fr) minmax(320px, 1fr)" in css
    assert ".stock-insight-panel" in css
    assert ".compact-detail" in css
    assert ".condition-list" in css
    assert ".playbook-details" in css
    assert ".chart-zoom-button" in css
    assert ".chart-lightbox" in css
    assert ".lightbox-open" in css
    assert ".chart-note" in css
    assert ".level-table" in css
    assert ".price-rail-note" in css
    assert "@media print" in css
    assert "break-inside: avoid" in css
    assert ".side-nav" in css
    assert ".export-button" in css
    assert "details.collapsible:not([open]) > .collapsible-body" in css
    assert "details.playbook-details:not([open])" in css


def test_html_export_pdf_opens_collapsed_sections_before_print():
    js = lstock_report.HTML_REPORT_JS

    assert "openCollapsibleSectionsForExport" in js
    assert "openPlaybooksForExport" in js
    assert "details.collapsible" in js
    assert "details.playbook-details" in js
    assert "setAttribute(\"open\", \"\")" in js
    assert "window.print()" in js
    assert "openCollapsibleSectionsForExport();" in js
    assert "openPlaybooksForExport();" in js
    assert "openChartLightbox" in js
    assert "closeChartLightbox" in js
    assert 'event.key === "Escape"' in js


def test_html_data_appendix_keeps_raw_diagnostics_collapsed():
    snapshot = report_snapshot_fixture()
    snapshot["stocks"]["items"][1]["fallback_from"] = {"source": "eastmoney_kline", "error": "disconnect"}
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "report.html"
        lstock_report.render_html_to_file(snapshot, output_path)
        html = output_path.read_text(encoding="utf-8")

    appendix_start = html.index('id="data-appendix"')
    appendix_html = html[appendix_start:]
    assert '<details class="report-section collapsible data-appendix" id="data-appendix">' in html
    assert "数据闸门" in appendix_html
    assert '"gate"' in appendix_html
    assert '"market"' in appendix_html
    assert '"emotion"' in appendix_html
    assert "sina_kline" in appendix_html
    assert '"chart_inputs"' in appendix_html
    assert '"identity": "position"' in appendix_html
    assert '"identity": "watchlist"' in appendix_html
    assert '"fallback_source": "eastmoney_kline"' in appendix_html
    assert '"candle_count": 80' in appendix_html
    assert '"has_ma5": true' in appendix_html
    assert '"has_ma20": true' in appendix_html
    assert '"has_ma40": true' in appendix_html
    assert '"price_ladder"' in appendix_html
    assert '"display_label": "上方压力"' in appendix_html


def test_playwright_pdf_runner_opens_collapsible_sections_before_pdf():
    events = []

    class FakePage:
        def goto(self, file_url, wait_until):
            events.append(("goto", file_url, wait_until))

        def emulate_media(self, media):
            events.append(("emulate_media", media))

        def evaluate(self, script):
            events.append(("evaluate", script))

        def pdf(self, **kwargs):
            events.append(("pdf", kwargs))

    class FakeBrowser:
        def new_page(self, **kwargs):
            events.append(("new_page", kwargs))
            return FakePage()

        def close(self):
            events.append(("close",))

    class FakeChromium:
        def launch(self):
            events.append(("launch",))
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeContext:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, *args):
            return False

    with tempfile.TemporaryDirectory() as tmpdir:
        report_path = Path(tmpdir) / "report.html"
        output_path = Path(tmpdir) / "report.pdf"
        report_path.write_text("<!doctype html>", encoding="utf-8")
        with patch.dict("sys.modules", {"playwright.sync_api": type("M", (), {"sync_playwright": lambda: FakeContext()})}):
            lstock_report._playwright_pdf_runner(report_path, output_path)

    evaluate_events = [event for event in events if event[0] == "evaluate"]
    assert evaluate_events
    assert "details.collapsible" in evaluate_events[0][1]
    assert "details.playbook-details" in evaluate_events[0][1]
    assert "setAttribute('open', '')" in evaluate_events[0][1]
    assert [event[0] for event in events].index("evaluate") < [event[0] for event in events].index("pdf")


def test_html_report_escapes_hostile_stock_identity_and_gate_status():
    snapshot = json.loads(json.dumps(report_snapshot_fixture(), ensure_ascii=False))
    hostile_name = '<script>alert(1)</script>'
    hostile_code = '"><script>alert(2)</script>'
    snapshot["state"]["positions"][0]["name"] = hostile_name
    snapshot["state"]["positions"][0]["code"] = hostile_code
    snapshot["stocks"]["items"][0]["name"] = hostile_name
    snapshot["stocks"]["items"][0]["code"] = hostile_code

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "report.html"
        lstock_report.render_html_to_file(snapshot, output_path)
        html = output_path.read_text(encoding="utf-8")

        assert hostile_name not in html
        assert hostile_code not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "&quot;&gt;&lt;script&gt;alert(2)&lt;/script&gt;" in html

        snapshot["gate"]["status"] = '"><script>alert(3)</script>'
        blocked_path = Path(tmpdir) / "blocked.html"
        lstock_report.render_html_to_file(snapshot, blocked_path)
        blocked_html = blocked_path.read_text(encoding="utf-8")

        assert snapshot["gate"]["status"] not in blocked_html
        assert "Gate &quot;&gt;&lt;script&gt;alert(3)&lt;/script&gt;" in blocked_html


def test_html_data_block_report_includes_chrome_task_details_without_trading_sections():
    snapshot = {
        "gate": {
            "status": "BLOCK",
            "blocks": [{"group": "funds", "reason": "python_source_requires_chrome_fallback", "missing": ["etf_scale_change"]}],
        },
        "chrome_tasks": [
            {
                "group": "funds",
                "name": "ETF 规模变化",
                "url": "https://www.jisilu.cn/data/etf/?q=<script>alert(1)</script>",
                "override_path": "cache/run_logs/source-overrides.json",
                "override_key": "funds",
                "expected_status": "PASS",
                "success_criteria": "包含 ETF 规模变化字段",
                "required_fields": ["etf_scale_change", "trade_date"],
                "example_override": {"etf_scale_change": "净流入", "note": "<unsafe>"},
            }
        ],
        "state": {
            "positions": [{"code": "301205", "name": "联特科技"}],
            "watchlist": [{"code": "000636", "name": "风华高科"}],
        },
    }

    html = lstock_report.render_data_block_html(snapshot)

    assert "l-stock 补数报告" in html
    assert "https://www.jisilu.cn/data/etf/?q=&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "cache/run_logs/source-overrides.json" in html
    assert "override_key" in html
    assert "funds" in html
    assert "expected_status" in html
    assert "PASS" in html
    assert "success_criteria" in html
    assert "包含 ETF 规模变化字段" in html
    assert "required_fields" in html
    assert "etf_scale_change, trade_date" in html
    assert "example_override" in html
    assert "&lt;unsafe&gt;" in html
    assert "不是交易报告" in html
    assert 'class="app-shell app-shell-single"' in html
    assert 'class="side-nav"' not in html
    assert 'class="export-button"' not in html
    assert "导出 PDF" not in html
    assert "个股动作表" not in html
    assert "持仓诊断" not in html
    assert "交易摘要" not in html
    assert '<table class="action-table">' not in html


def test_report_cli_accepts_html_markdown_and_pdf_commands():
    html_args = lstock_report.parse_args(["render-html", "--snapshot", "snap.json", "--output", "report.html"])
    md_args = lstock_report.parse_args(["render-md", "--snapshot", "snap.json", "--output", "report.md", "--with-images"])
    pdf_args = lstock_report.parse_args(["export-pdf", "--report", "report.html", "--output", "report.pdf"])

    assert html_args.command == "render-html"
    assert md_args.command == "render-md"
    assert md_args.with_images is True
    assert pdf_args.command == "export-pdf"


def test_report_main_export_pdf_dispatches_without_reading_snapshot():
    with patch.object(lstock_report.Path, "read_text", side_effect=AssertionError("snapshot should not be read")):
        with patch.object(lstock_report, "export_pdf_from_html", return_value={"format": "pdf"}) as export_pdf:
            status = lstock_report.main(["export-pdf", "--report", "report.html", "--output", "report.pdf"])

    assert status == 0
    export_pdf.assert_called_once_with(Path("report.html"), Path("report.pdf"))


def test_pdf_export_writes_to_output_path_with_injected_runner():
    calls = []

    def fake_runner(report_path, output_path):
        calls.append((report_path, output_path))
        output_path.write_bytes(b"%PDF-1.4\nfake\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        report_path = Path(tmpdir) / "report.html"
        output_path = Path(tmpdir) / "output" / "report.pdf"
        report_path.write_text("<!doctype html><title>x</title>", encoding="utf-8")

        payload = lstock_report.export_pdf_from_html(report_path, output_path, runner=fake_runner)

        assert payload["format"] == "pdf"
        assert payload["report"] == str(report_path)
        assert payload["pdf"] == str(output_path)
        assert output_path.read_bytes().startswith(b"%PDF-")
        assert calls == [(report_path, output_path)]


def test_pdf_export_fails_without_deleting_html_when_report_missing():
    with tempfile.TemporaryDirectory() as tmpdir:
        missing = Path(tmpdir) / "missing.html"
        output_path = Path(tmpdir) / "output" / "missing.pdf"
        try:
            lstock_report.export_pdf_from_html(missing, output_path, runner=lambda _report, output: output.write_bytes(b"x"))
        except FileNotFoundError as error:
            assert str(missing) in str(error)
        else:
            raise AssertionError("expected FileNotFoundError")
        assert not output_path.exists()


def test_pdf_export_fails_when_runner_does_not_create_output():
    with tempfile.TemporaryDirectory() as tmpdir:
        report_path = Path(tmpdir) / "report.html"
        output_path = Path(tmpdir) / "output" / "report.pdf"
        report_path.write_text("<!doctype html><title>x</title>", encoding="utf-8")

        try:
            lstock_report.export_pdf_from_html(report_path, output_path, runner=lambda _report, _output: None)
        except RuntimeError as error:
            assert "PDF export did not create output" in str(error)
            assert str(output_path) in str(error)
        else:
            raise AssertionError("expected RuntimeError")


def test_pdf_export_fails_when_runner_writes_invalid_pdf_output():
    invalid_outputs = [b"", b"not a pdf"]

    for invalid_output in invalid_outputs:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "report.html"
            output_path = Path(tmpdir) / "output" / "report.pdf"
            report_path.write_text("<!doctype html><title>x</title>", encoding="utf-8")

            def fake_runner(_report, output):
                output.write_bytes(invalid_output)

            try:
                lstock_report.export_pdf_from_html(report_path, output_path, runner=fake_runner)
            except RuntimeError as error:
                assert "PDF export produced invalid PDF output" in str(error)
                assert str(output_path) in str(error)
            else:
                raise AssertionError("expected RuntimeError")


def test_report_main_legacy_render_dispatches_markdown_with_images():
    snapshot = {"gate": {"status": "PASS"}, "state": {}, "stocks": {"items": []}}
    with tempfile.TemporaryDirectory() as tmpdir:
        snapshot_path = Path(tmpdir) / "snap.json"
        output_path = Path(tmpdir) / "report.md"
        snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

        with patch.object(lstock_report, "render_markdown_to_file", return_value={"format": "markdown"}) as render_markdown:
            status = lstock_report.main(["render", "--snapshot", str(snapshot_path), "--output", str(output_path)])

    assert status == 0
    render_markdown.assert_called_once_with(snapshot, output_path, include_images=True)


def test_report_main_render_md_dispatches_clean_markdown_by_default():
    snapshot = {"gate": {"status": "PASS"}, "state": {}, "stocks": {"items": []}}
    with tempfile.TemporaryDirectory() as tmpdir:
        snapshot_path = Path(tmpdir) / "snap.json"
        output_path = Path(tmpdir) / "report.md"
        snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

        with patch.object(lstock_report, "render_markdown_to_file", return_value={"format": "markdown"}) as render_markdown:
            status = lstock_report.main(["render-md", "--snapshot", str(snapshot_path), "--output", str(output_path)])

    assert status == 0
    render_markdown.assert_called_once_with(snapshot, output_path, include_images=False)


def test_report_main_render_md_with_images_dispatches_markdown_with_images():
    snapshot = {"gate": {"status": "PASS"}, "state": {}, "stocks": {"items": []}}
    with tempfile.TemporaryDirectory() as tmpdir:
        snapshot_path = Path(tmpdir) / "snap.json"
        output_path = Path(tmpdir) / "report.md"
        snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

        with patch.object(lstock_report, "render_markdown_to_file", return_value={"format": "markdown"}) as render_markdown:
            status = lstock_report.main(
                ["render-md", "--snapshot", str(snapshot_path), "--output", str(output_path), "--with-images"]
            )

    assert status == 0
    render_markdown.assert_called_once_with(snapshot, output_path, include_images=True)


def test_report_main_render_html_dispatches_html_renderer():
    snapshot = {"gate": {"status": "PASS"}, "state": {}, "stocks": {"items": []}}
    with tempfile.TemporaryDirectory() as tmpdir:
        snapshot_path = Path(tmpdir) / "snap.json"
        output_path = Path(tmpdir) / "report.html"
        snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

        with patch.object(lstock_report, "render_html_to_file", return_value={"format": "html"}) as render_html:
            status = lstock_report.main(["render-html", "--snapshot", str(snapshot_path), "--output", str(output_path)])

    assert status == 0
    render_html.assert_called_once_with(snapshot, output_path)


def test_lstock_cli_uses_html_report_names_and_export_commands():
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        html_path = lstock_cli.report_name(workspace, "2026-06-23-2359", "PASS")
        block_path = lstock_cli.report_name(workspace, "2026-06-23-2359", "BLOCK")

        assert html_path.name == "2026-06-23-2359.html"
        assert block_path.name == "2026-06-23-2359-data-block.html"

    md_args = lstock_cli.parse_args(["export-md", "--workspace", ".", "--snapshot", "cache/run_logs/a-snapshot.json"])
    pdf_args = lstock_cli.parse_args(["export-pdf", "--workspace", ".", "--report", "reports/a.html"])

    assert md_args.command == "export-md"
    assert pdf_args.command == "export-pdf"
    assert lstock_cli.export_stem(Path("cache/run_logs/a-snapshot.json")) == "a"
    assert lstock_cli.export_stem(Path("cache/run_logs/a-snapshot-02.json")) == "a-02"


def test_lstock_cli_export_md_dispatches_render_md_with_default_output_and_images():
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir).resolve()
        captured = {}
        child_payload = {"status": "OK", "format": "markdown"}

        def fake_run_captured(command):
            captured["command"] = command
            return FakeCompletedProcess(json.dumps(child_payload))

        stdout = StringIO()
        with patch.object(lstock_cli, "run_captured", side_effect=fake_run_captured):
            with contextlib.redirect_stdout(stdout):
                status = lstock_cli.main(
                    [
                        "export-md",
                        "--workspace",
                        str(workspace),
                        "--snapshot",
                        "cache/run_logs/a-snapshot.json",
                        "--with-images",
                    ]
                )

        assert status == 0
        assert captured["command"] == [
            lstock_cli.sys.executable,
            str(lstock_cli.REPORT_SCRIPT),
            "render-md",
            "--snapshot",
            str(workspace / "cache" / "run_logs" / "a-snapshot.json"),
            "--output",
            str(workspace / "reports" / "output" / "a.md"),
            "--with-images",
        ]
        assert json.loads(stdout.getvalue()) == child_payload


def test_lstock_cli_export_pdf_dispatches_export_pdf_with_default_output():
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir).resolve()
        captured = {}
        child_payload = {"status": "OK", "format": "pdf"}

        def fake_run_captured(command):
            captured["command"] = command
            return FakeCompletedProcess(json.dumps(child_payload))

        stdout = StringIO()
        with patch.object(lstock_cli, "run_captured", side_effect=fake_run_captured):
            with contextlib.redirect_stdout(stdout):
                status = lstock_cli.main(
                    [
                        "export-pdf",
                        "--workspace",
                        str(workspace),
                        "--report",
                        "reports/a.html",
                    ]
                )

        assert status == 0
        assert captured["command"] == [
            lstock_cli.sys.executable,
            str(lstock_cli.REPORT_SCRIPT),
            "export-pdf",
            "--report",
            str(workspace / "reports" / "a.html"),
            "--output",
            str(workspace / "reports" / "output" / "a.pdf"),
        ]
        assert json.loads(stdout.getvalue()) == child_payload


def test_lstock_cli_export_pdf_anchors_relative_output_to_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir).resolve()
        captured = {}

        def fake_run_captured(command):
            captured["command"] = command
            return FakeCompletedProcess(json.dumps({"status": "OK", "format": "pdf"}))

        with patch.object(lstock_cli, "run_captured", side_effect=fake_run_captured):
            status = lstock_cli.main(
                [
                    "export-pdf",
                    "--workspace",
                    str(workspace),
                    "--report",
                    "reports/a.html",
                    "--output",
                    "exports/a.pdf",
                ]
            )

        assert status == 0
        assert str(workspace / "exports" / "a.pdf") in captured["command"]


def main():
    for name, func in sorted(globals().items()):
        if name.startswith("test_"):
            func()
            print(f"PASS {name}")


if __name__ == "__main__":
    main()
