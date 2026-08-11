#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A-share ETF dashboard.

Run:
  python3 etf_dashboard.py
  python3 etf_dashboard.py --serve

The script creates reports/etf_dashboard.html.
Tushare mode uses fund_daily + fund_share to estimate ETF subscription flow:
share change * close price. Eastmoney remains as a fallback data source.
"""

import argparse
import datetime as dt
import html
import importlib.util
import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPORT_DIR = ROOT / "reports"
HTML_PATH = REPORT_DIR / "etf_dashboard.html"
CACHE_DIR = ROOT / "data_cache"
SCALE_CACHE_PATH = CACHE_DIR / "exchange_scale_snapshot.json"
KLINE_CACHE_PATH = CACHE_DIR / "kline_cache.json"
BENCHMARK_CODE = "510300"
BENCHMARK_NAME = "沪深300ETF"
RELATIVE_WEIGHTS = {"r5": 0.25, "r20": 0.45, "r60": 0.30}

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
}

TUSHARE_API_URL = "http://api.tushare.pro"
KLINE_CACHE_LOCK = threading.Lock()
BAOSTOCK_LOCK = threading.Lock()


ETF_GROUPS = {
    "宽基": [
        ("510300", "沪深300ETF"),
        ("510050", "上证50ETF"),
        ("510500", "中证500ETF"),
        ("512100", "中证1000ETF"),
        ("588000", "科创50ETF"),
        ("159915", "创业板ETF"),
        ("159338", "中证A500ETF"),
    ],
    "科技成长": [
        ("515880", "通信ETF"),
        ("159995", "芯片ETF"),
        ("512760", "芯片ETF"),
        ("159516", "半导体设备ETF"),
        ("588200", "科创芯片ETF"),
        ("159819", "人工智能ETF"),
        ("159530", "机器人ETF"),
        ("159538", "信创ETF"),
        ("159558", "半导体设备ETF易方达"),
    ],
    "新能源/制造": [
        ("515790", "光伏ETF"),
        ("159755", "电池ETF"),
        ("516160", "新能源ETF"),
        ("159326", "电网设备ETF"),
        ("159611", "电力ETF"),
        ("159713", "稀土ETF"),
        ("159840", "锂电池ETF"),
    ],
    "周期资源": [
        ("512400", "有色金属ETF"),
        ("159930", "能源ETF"),
        ("515220", "煤炭ETF"),
        ("159985", "豆粕ETF"),
        ("518880", "黄金ETF"),
        ("159980", "有色ETF"),
    ],
    "金融地产": [
        ("512880", "证券ETF"),
        ("512800", "银行ETF"),
        ("159940", "金融地产ETF"),
        ("515060", "地产ETF"),
        ("512200", "房地产ETF"),
    ],
    "消费医药": [
        ("159928", "消费ETF"),
        ("515170", "食品饮料ETF"),
        ("159996", "家电ETF"),
        ("512010", "医药ETF"),
        ("515120", "创新药ETF"),
        ("159992", "创新药ETF"),
        ("512170", "医疗ETF"),
    ],
    "港股/跨境": [
        ("513130", "恒生科技ETF"),
        ("513330", "恒生互联网ETF"),
        ("159605", "中概互联ETF"),
        ("513060", "恒生医疗ETF"),
        ("513100", "纳指ETF"),
        ("513500", "标普500ETF"),
        ("159866", "日经ETF"),
    ],
    "红利防御": [
        ("510880", "红利ETF"),
        ("512890", "红利低波ETF"),
        ("515080", "中证红利ETF"),
        ("511010", "国债ETF"),
        ("511260", "十年国债ETF"),
    ],
}


def secid_for_code(code):
    if code.startswith(("5", "6", "9")):
        return "1." + code
    return "0." + code


def ts_code_for_code(code):
    if code.startswith(("5", "6", "9")):
        return code + ".SH"
    return code + ".SZ"


def load_tushare_token(cli_token=None):
    if cli_token:
        return cli_token.strip()
    env_token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if env_token:
        return env_token
    token_path = ROOT / "config" / "tushare_token.txt"
    if token_path.exists():
        return token_path.read_text(encoding="utf-8").strip()
    return ""


def fetch_json(url, timeout=15, retries=3):
    last_error = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HTTP_HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw)
        except Exception as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(0.8 * (attempt + 1))
    raise last_error


def load_kline_cache():
    if not KLINE_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(KLINE_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def cache_entry_rows(entry):
    if valid_klines(entry):
        return entry
    if isinstance(entry, dict):
        rows = entry.get("rows")
        if valid_klines(rows):
            return rows
    return []


def valid_klines(rows):
    if not isinstance(rows, list):
        return False
    required = {"date", "close", "high", "low"}
    return bool(rows) and all(isinstance(row, dict) and required.issubset(row) for row in rows)


def save_kline_cache(cache):
    CACHE_DIR.mkdir(exist_ok=True)
    KLINE_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def post_json(url, payload, timeout=20, retries=3):
    body = json.dumps(payload).encode("utf-8")
    headers = dict(HTTP_HEADERS)
    headers["Content-Type"] = "application/json"
    last_error = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw)
        except Exception as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(0.8 * (attempt + 1))
    raise last_error


def tushare_query(token, api_name, params=None, fields=""):
    payload = {
        "api_name": api_name,
        "token": token,
        "params": params or {},
        "fields": fields,
    }
    data = post_json(TUSHARE_API_URL, payload)
    if data.get("code") != 0:
        raise RuntimeError(f"{api_name}: {data.get('msg') or data}")
    block = data.get("data") or {}
    field_names = block.get("fields") or []
    items = block.get("items") or []
    return [dict(zip(field_names, item)) for item in items]


def em_quote_all_etfs():
    params = {
        "pn": "1",
        "pz": "5000",
        "po": "1",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "b:MK0021,b:MK0022,b:MK0023,b:MK0024",
        "fields": "f12,f14,f2,f3,f4,f5,f6,f15,f16,f17,f18,f62,f184",
    }
    url = "https://push2.eastmoney.com/api/qt/clist/get?" + urllib.parse.urlencode(params)
    data = fetch_json(url)
    diff = (data.get("data") or {}).get("diff") or []
    if isinstance(diff, dict):
        diff = list(diff.values())
    return {str(item.get("f12")): item for item in diff if item.get("f12")}


def em_daily_kline(code, bars=90):
    params = {
        "secid": secid_for_code(code),
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "1",
        "end": "20500101",
        "lmt": str(bars),
    }
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get?" + urllib.parse.urlencode(params)
    data = fetch_json(url, timeout=8, retries=2)
    klines = (data.get("data") or {}).get("klines") or []
    rows = []
    for line in klines:
        parts = line.split(",")
        if len(parts) < 11:
            continue
        try:
            rows.append(
                {
                    "date": parts[0],
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": float(parts[5]),
                    "amount": float(parts[6]),
                    "pct": float(parts[8]),
                }
            )
        except ValueError:
            continue
    return rows


def akshare_etf_daily_kline(code, bars=90):
    if importlib.util.find_spec("akshare") is None:
        raise RuntimeError("未安装 akshare，无法使用备用历史行情源")
    import akshare as ak

    start_date = (dt.date.today() - dt.timedelta(days=max(bars * 3, 260))).strftime("%Y%m%d")
    df = ak.fund_etf_hist_em(
        symbol=code,
        period="daily",
        start_date=start_date,
        end_date="20500101",
        adjust="qfq",
    )
    if df is None or df.empty:
        return []

    rows = []
    for _, item in df.tail(bars).iterrows():
        try:
            rows.append(
                {
                    "date": str(item.get("日期")).replace("-", ""),
                    "open": float(item.get("开盘")),
                    "close": float(item.get("收盘")),
                    "high": float(item.get("最高")),
                    "low": float(item.get("最低")),
                    "volume": float(item.get("成交量") or 0),
                    "amount": float(item.get("成交额") or 0),
                    "pct": float(item.get("涨跌幅") or 0),
                }
            )
        except (TypeError, ValueError):
            continue
    return rows


def akshare_sina_daily_kline(code, bars=90):
    if importlib.util.find_spec("akshare") is None:
        raise RuntimeError("未安装 akshare，无法使用新浪备用历史行情源")
    import akshare as ak

    symbol = ("sh" if code.startswith(("5", "6", "9")) else "sz") + code
    df = ak.fund_etf_hist_sina(symbol=symbol)
    if df is None or df.empty:
        return []

    rows = []
    previous_close = None
    for _, item in df.tail(bars).iterrows():
        try:
            close = float(item.get("close"))
            pct = None
            if previous_close not in (None, 0):
                pct = (close / previous_close - 1) * 100
            rows.append(
                {
                    "date": str(item.get("date")),
                    "open": float(item.get("open")),
                    "close": close,
                    "high": float(item.get("high")),
                    "low": float(item.get("low")),
                    "volume": float(item.get("volume") or 0),
                    "amount": float(item.get("amount") or 0),
                    "pct": pct,
                }
            )
            previous_close = close
        except (TypeError, ValueError):
            continue
    return rows


def baostock_daily_kline(code, bars=90):
    if importlib.util.find_spec("baostock") is None:
        raise RuntimeError("未安装 baostock，无法使用 BaoStock 备用历史行情源")
    import baostock as bs
    import pandas as pd

    bs_code = ("sh." if code.startswith(("5", "6", "9")) else "sz.") + code
    start_date = (dt.date.today() - dt.timedelta(days=max(bars * 3, 260))).isoformat()
    end_date = dt.date.today().isoformat()
    fields = "date,code,open,high,low,close,preclose,volume,amount,pctChg,turn"
    with BAOSTOCK_LOCK:
        login_result = bs.login()
        try:
            if login_result.error_code != "0":
                raise RuntimeError(login_result.error_msg)
            result = bs.query_history_k_data_plus(
                bs_code,
                fields,
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="2",
            )
            data = []
            while result.error_code == "0" and result.next():
                data.append(result.get_row_data())
            if result.error_code != "0":
                raise RuntimeError(result.error_msg)
            df = pd.DataFrame(data, columns=result.fields)
        finally:
            bs.logout()

    if df.empty:
        return []

    rows = []
    for _, item in df.tail(bars).iterrows():
        try:
            rows.append(
                {
                    "date": str(item.get("date")),
                    "open": float(item.get("open")),
                    "close": float(item.get("close")),
                    "high": float(item.get("high")),
                    "low": float(item.get("low")),
                    "volume": float(item.get("volume") or 0),
                    "amount": float(item.get("amount") or 0),
                    "pct": float(item.get("pctChg") or 0),
                }
            )
        except (TypeError, ValueError):
            continue
    return rows


def save_kline_rows(code, source, rows):
    with KLINE_CACHE_LOCK:
        cache = load_kline_cache()
        cache[code] = {
            "updated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": source,
            "rows": rows,
        }
        save_kline_cache(cache)


def cached_em_daily_kline(code, bars=90):
    cache = load_kline_cache()
    try:
        rows = em_daily_kline(code, bars=bars)
        if rows:
            save_kline_rows(code, "eastmoney", rows)
            return rows, None
    except Exception as exc:
        em_error = exc
        try:
            rows = akshare_etf_daily_kline(code, bars=bars)
            if rows:
                save_kline_rows(code, "akshare_fund_etf_hist_em", rows)
                return rows, f"{code}: 东方财富K线失败，已使用 AKShare 备用行情：{em_error}"
        except Exception as fallback_exc:
            try:
                rows = baostock_daily_kline(code, bars=bars)
                if rows:
                    save_kline_rows(code, "baostock", rows)
                    return rows, f"{code}: 东方财富K线失败，已使用 BaoStock 备用行情：{em_error}"
            except Exception as baostock_exc:
                try:
                    rows = akshare_sina_daily_kline(code, bars=bars)
                    if rows:
                        save_kline_rows(code, "akshare_fund_etf_hist_sina", rows)
                        return rows, f"{code}: 东方财富/BaoStock K线失败，已使用新浪备用行情：{em_error}"
                except Exception as sina_exc:
                    cached = cache_entry_rows(cache.get(code))
                    if cached:
                        return cached, f"{code}: K线实时获取失败，已使用缓存：{em_error}；备用源失败：{fallback_exc}；BaoStock失败：{baostock_exc}；新浪失败：{sina_exc}"
                    return [], f"{code}: K线获取失败：{em_error}；备用源失败：{fallback_exc}；BaoStock失败：{baostock_exc}；新浪失败：{sina_exc}"
                cached = cache_entry_rows(cache.get(code))
                if cached:
                    return cached, f"{code}: K线实时获取失败，已使用缓存：{em_error}；备用源失败：{fallback_exc}；BaoStock失败：{baostock_exc}"
                return [], f"{code}: K线获取失败：{em_error}；备用源失败：{fallback_exc}；BaoStock失败：{baostock_exc}"
            cached = cache_entry_rows(cache.get(code))
            if cached:
                return cached, f"{code}: K线实时获取失败，已使用缓存：{em_error}；备用源失败：{fallback_exc}"
            return [], f"{code}: K线获取失败：{em_error}；备用源失败：{fallback_exc}"
        cached = cache_entry_rows(cache.get(code))
        if cached:
            return cached, f"{code}: K线实时获取失败，已使用缓存：{em_error}"
        return [], f"{code}: K线获取失败：{em_error}"
    cached = cache_entry_rows(cache.get(code))
    if cached:
        return cached, f"{code}: K线实时为空，已使用缓存"
    return [], f"{code}: K线为空"


def yyyymmdd_days_ago(days):
    return (dt.date.today() - dt.timedelta(days=days)).strftime("%Y%m%d")


def tushare_daily_kline(token, code, days=210):
    ts_code = ts_code_for_code(code)
    fields = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"
    rows = tushare_query(
        token,
        "fund_daily",
        {"ts_code": ts_code, "start_date": yyyymmdd_days_ago(days)},
        fields,
    )
    klines = []
    for item in rows:
        try:
            klines.append(
                {
                    "date": str(item.get("trade_date")),
                    "open": float(item.get("open")),
                    "close": float(item.get("close")),
                    "high": float(item.get("high")),
                    "low": float(item.get("low")),
                    "volume": float(item.get("vol") or 0),
                    "amount": float(item.get("amount") or 0),
                    "pct": float(item.get("pct_chg") or 0),
                }
            )
        except (TypeError, ValueError):
            continue
    return sorted(klines, key=lambda x: x["date"])


def tushare_fund_share(token, code, days=210):
    ts_code = ts_code_for_code(code)
    rows = tushare_query(
        token,
        "fund_share",
        {"ts_code": ts_code, "start_date": yyyymmdd_days_ago(days)},
        "ts_code,trade_date,fd_share",
    )
    parsed = []
    for item in rows:
        try:
            parsed.append({"date": str(item.get("trade_date")), "fd_share": float(item.get("fd_share"))})
        except (TypeError, ValueError):
            continue
    return sorted(parsed, key=lambda x: x["date"])


def share_flow_yi(share_rows, close):
    if len(share_rows) < 2 or close is None:
        return None
    latest = share_rows[-1]["fd_share"]
    previous = share_rows[-2]["fd_share"]
    # fd_share is in 10k shares. close is CNY/share. Result is CNY 100m.
    return (latest - previous) * close / 10000


def share_change_pct(share_rows):
    if len(share_rows) < 2:
        return None
    previous = share_rows[-2]["fd_share"]
    if previous == 0:
        return None
    return (share_rows[-1]["fd_share"] / previous - 1) * 100


def load_scale_cache():
    if not SCALE_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(SCALE_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_scale_cache(snapshot):
    CACHE_DIR.mkdir(exist_ok=True)
    SCALE_CACHE_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_sse_scale_by_date(date_text):
    import akshare as ak

    df = ak.fund_etf_scale_sse(date=date_text)
    result = {}
    for _, item in df.iterrows():
        code = str(item.get("基金代码", "")).zfill(6)
        share = safe_num(item.get("基金份额"))
        if code and share is not None:
            result[code] = {
                "share": share,
                "name": str(item.get("基金简称", "")),
                "date": str(item.get("统计日期", date_text)),
                "source": "SSE",
            }
    return result


def fetch_recent_sse_scales(max_days=20):
    current = None
    previous = None
    errors = []
    today = dt.date.today()
    for offset in range(max_days):
        day = today - dt.timedelta(days=offset)
        date_text = day.strftime("%Y%m%d")
        try:
            scale = fetch_sse_scale_by_date(date_text)
        except Exception as exc:
            errors.append(f"上交所ETF份额 {date_text} 获取失败：{exc}")
            continue
        if not scale:
            continue
        if current is None:
            current = scale
        else:
            previous = scale
            break
    return current or {}, previous or {}, errors


def fetch_szse_scale_latest():
    import akshare as ak

    df = ak.fund_etf_scale_szse()
    result = {}
    date_text = dt.date.today().isoformat()
    for _, item in df.iterrows():
        code = str(item.get("基金代码", "")).zfill(6)
        share = safe_num(item.get("基金份额"))
        if code and share is not None:
            result[code] = {
                "share": share,
                "name": str(item.get("基金简称", "")),
                "date": date_text,
                "source": "SZSE",
            }
    return result


def apply_exchange_scale_flows(rows):
    errors = []
    if not importlib.util.find_spec("akshare"):
        return ["未安装 AKShare，无法使用交易所ETF份额接口。"]

    old_cache = load_scale_cache()
    old_by_code = old_cache.get("by_code", {})
    new_by_code = {}

    try:
        sse_current, sse_previous, sse_errors = fetch_recent_sse_scales()
        errors.extend(sse_errors[:3])
    except Exception as exc:
        sse_current, sse_previous = {}, {}
        errors.append(f"上交所ETF份额接口获取失败：{exc}")

    try:
        szse_current = fetch_szse_scale_latest()
    except Exception as exc:
        szse_current = {}
        errors.append(f"深交所ETF份额接口获取失败：{exc}")

    for code, item in sse_current.items():
        new_by_code[code] = item
    for code, item in szse_current.items():
        new_by_code[code] = item

    updated = 0
    for row in rows:
        code = row.get("code")
        current = new_by_code.get(code)
        if not current:
            continue
        previous = sse_previous.get(code) if current.get("source") == "SSE" else old_by_code.get(code)
        row["scale_share"] = current.get("share")
        row["scale_date"] = current.get("date")
        row["scale_source"] = current.get("source")
        if not previous or previous.get("share") in (None, 0) or row.get("price") is None:
            continue
        share_delta = current["share"] - previous["share"]
        row["main_flow_yi"] = share_delta * row["price"] / 100000000
        row["main_flow_pct"] = share_delta / previous["share"] * 100
        row["flow_source"] = f"{current.get('source')}份额变化"
        row["prev_scale_date"] = previous.get("date")
        row["score"] = score(row)
        row["state"] = classify(row)
        updated += 1

    if new_by_code:
        save_scale_cache(
            {
                "updated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "by_code": new_by_code,
            }
        )
    if updated:
        errors.append(f"已用交易所ETF份额变化计算资金流：{updated}只。")
    elif new_by_code:
        errors.append("已获取交易所ETF份额，但部分ETF缺少上一期份额或价格，暂未形成资金流。深交所ETF需第二次运行后用缓存计算。")
    return errors


def pct_return(klines, days):
    if len(klines) <= days:
        return None
    pct_values = [row.get("pct") for row in klines[-days:]]
    if len(pct_values) == days and all(value is not None for value in pct_values):
        compounded = 1.0
        for value in pct_values:
            compounded *= 1 + value / 100
        return (compounded - 1) * 100
    latest = klines[-1].get("close")
    previous = klines[-1 - days].get("close")
    if latest is None or previous is None:
        return None
    if previous == 0:
        return None
    return (latest / previous - 1) * 100


def latest_pct_from_klines(klines):
    if not klines:
        return None
    latest_pct = klines[-1].get("pct")
    if latest_pct is not None:
        return latest_pct
    if len(klines) < 2:
        return None
    latest = klines[-1].get("close")
    previous = klines[-2].get("close")
    if latest is None or previous in (None, 0):
        return None
    return (latest / previous - 1) * 100


def moving_position(klines, window=60):
    if len(klines) < 2:
        return None
    rows = klines[-window:]
    highs = [row.get("high") for row in rows if row.get("high") is not None]
    lows = [row.get("low") for row in rows if row.get("low") is not None]
    close = klines[-1].get("close")
    if not highs or not lows or close is None:
        return None
    high = max(highs)
    low = min(lows)
    if high == low:
        return None
    return (close - low) / (high - low) * 100


def safe_num(value):
    if value in (None, "-", ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def money_yi(value):
    num = safe_num(value)
    if num is None:
        return None
    return num / 100000000


def format_pct(value):
    if value is None:
        return "-"
    return f"{value:+.2f}%"


def format_yi(value):
    if value is None:
        return "-"
    return f"{value:+.2f}亿"


def format_score_value(value):
    if value is None:
        return "-"
    return f"{value:+.2f}"


def trend_marker(row):
    r20 = row.get("r20")
    r60 = row.get("r60")
    score_value = row.get("relative_score")
    flow = row.get("main_flow_yi")
    if r20 is None or r60 is None or score_value is None:
        return "·"
    if r20 > 0 and r60 > 0 and score_value >= 5:
        return "📈"
    if r20 > 0 and r60 > 0:
        return "🔥" if (flow or 0) > 0 else "↗"
    if r20 > 0 and r60 <= 0:
        return "↗"
    if r20 <= 0 and r60 > 0:
        return "➡"
    if r20 < 0 and r60 < 0:
        return "📉"
    return "➡"


def normalize_date_text(value):
    text = str(value or "")
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return text or "-"


def is_stale_date(value):
    normalized = normalize_date_text(value)
    try:
        day = dt.datetime.strptime(normalized, "%Y-%m-%d").date()
    except ValueError:
        return False
    return day < dt.date.today()


def format_market_date(value):
    normalized = normalize_date_text(value)
    cls = "date-stale" if is_stale_date(value) else "date-fresh"
    return f"<span class='date-tag {cls}'>{html.escape(normalized)}</span>"


def format_flow_sum(value, count, total):
    if count == 0:
        return "缺失"
    text = format_yi(value)
    if count < total:
        return f"{text} ({count}/{total})"
    return text


def format_amount_yi(value):
    num = money_yi(value)
    if num is None:
        return "-"
    return f"{num:.2f}亿"


def classify(row):
    r5 = row.get("rel5") if row.get("rel5") is not None else row.get("r5")
    r20 = row.get("rel20") if row.get("rel20") is not None else row.get("r20")
    r60 = row.get("rel60") if row.get("rel60") is not None else row.get("r60")
    flow = row.get("main_flow_yi") or 0
    pos = row.get("pos60")

    if r5 is None or r20 is None:
        return "数据不足"
    if r5 > 0 and r20 > 0 and (r60 or 0) > 0 and flow > 0:
        return "资金+相对强势共振"
    if r5 > 0 and r20 > 0 and (r60 or 0) > 0:
        return "相对强势"
    if r5 < 0 and r20 > 0 and (r60 or 0) > 0:
        return "相对强势内回调"
    if r5 > 0 and r20 < 0:
        return "相对超跌反弹"
    if flow > 0 and r5 <= 0:
        return "资金流入但价格承压"
    if flow < 0 and r5 > 0:
        return "上涨但资金背离"
    if pos is not None and pos > 85:
        return "高位强势/防追高"
    if pos is not None and pos < 20:
        return "低位弱势/等确认"
    return "震荡观察"


def relative_value(row, key):
    value = row.get(key)
    benchmark = row.get("benchmark", {}).get(key)
    if value is None or benchmark is None:
        return None
    return value - benchmark


def relative_score(row):
    parts = []
    for key, weight in RELATIVE_WEIGHTS.items():
        value = relative_value(row, key)
        if value is not None:
            parts.append(value * weight)
    return sum(parts) if parts else None


def score(row):
    rel = row.get("relative_score")
    parts = [rel] if rel is not None else []
    flow = row.get("main_flow_yi")
    if flow is not None:
        parts.append(max(min(flow, 5), -5) * 0.15)
    return sum(parts)


def apply_relative_metrics(rows):
    benchmark = next((row for row in rows if row.get("code") == BENCHMARK_CODE), None)
    if not benchmark:
        benchmark = {}
    benchmark_data = {key: benchmark.get(key) for key in ("r5", "r20", "r60")}
    for row in rows:
        row["benchmark"] = benchmark_data
        row["rel5"] = relative_value(row, "r5")
        row["rel20"] = relative_value(row, "r20")
        row["rel60"] = relative_value(row, "r60")
        row["relative_score"] = relative_score(row)
        row["score"] = score(row)
        row["state"] = classify(row)
    return benchmark_data


def collect_eastmoney_data():
    errors = []
    try:
        quotes = em_quote_all_etfs()
    except Exception as exc:
        quotes = {}
        errors.append(f"ETF实时行情列表获取失败：{exc}")
    rows = []

    tasks = []
    for group, items in ETF_GROUPS.items():
        for code, fallback_name in items:
            tasks.append((group, code, fallback_name))

    kline_by_code = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_map = {executor.submit(cached_em_daily_kline, code): (code, fallback_name) for _, code, fallback_name in tasks}
        for future in as_completed(future_map):
            code, fallback_name = future_map[future]
            try:
                rows, warning = future.result()
                kline_by_code[code] = rows
                if warning:
                    errors.append(warning)
            except Exception as exc:
                kline_by_code[code] = []
                errors.append(f"{code} {fallback_name}: K线获取失败：{exc}")

    cache = load_kline_cache()
    for group, code, fallback_name in tasks:
        quote = quotes.get(code, {})
        klines = kline_by_code.get(code, [])
        if not valid_klines(klines):
            klines = cache_entry_rows(cache.get(code))
        latest = klines[-1] if klines else {}
        name = quote.get("f14") or fallback_name
        quote_pct = safe_num(quote.get("f3"))
        row = {
            "group": group,
            "code": code,
            "name": name,
            "price": safe_num(quote.get("f2")) or latest.get("close"),
            "pct": quote_pct if quote_pct is not None else latest_pct_from_klines(klines),
            "turnover": quote.get("f6") or latest.get("amount"),
            "main_flow_yi": None,
            "main_flow_pct": None,
            "r5": pct_return(klines, 5),
            "r20": pct_return(klines, 20),
            "r60": pct_return(klines, 60),
            "pos60": moving_position(klines, 60),
            "last_kline_date": klines[-1].get("date", "-") if klines else "-",
        }
        row["state"] = classify(row)
        row["score"] = score(row)
        rows.append(row)
    return rows, errors


def collect_tushare_data(token):
    errors = []
    rows = []
    if not token:
        return [], ["未配置 Tushare token。请把 token 放到 config/tushare_token.txt，或运行时加 --token。"]

    tasks = []
    for group, items in ETF_GROUPS.items():
        for code, fallback_name in items:
            tasks.append((group, code, fallback_name))

    first_code, first_name = tasks[0][1], tasks[0][2]
    try:
        first_daily = tushare_daily_kline(token, first_code)
    except Exception as exc:
        msg = str(exc)
        if "没有接口" in msg or "权限" in msg:
            return [], [f"Tushare fund_daily 预检失败：{msg}"]
        first_daily = []
        errors.append(f"{first_code} {first_name}: Tushare daily 预检失败：{exc}")

    try:
        first_share = tushare_fund_share(token, first_code)
    except Exception as exc:
        msg = str(exc)
        if "没有接口" in msg or "权限" in msg:
            return [], [f"Tushare fund_share 预检失败：{msg}"]
        first_share = []
        errors.append(f"{first_code} {first_name}: Tushare share 预检失败：{exc}")

    daily_by_code = {}
    share_by_code = {}
    daily_by_code[first_code] = first_daily
    share_by_code[first_code] = first_share
    with ThreadPoolExecutor(max_workers=6) as executor:
        future_map = {}
        for _, code, fallback_name in tasks:
            if code == first_code:
                continue
            future_map[executor.submit(tushare_daily_kline, token, code)] = ("daily", code, fallback_name)
            future_map[executor.submit(tushare_fund_share, token, code)] = ("share", code, fallback_name)
        for future in as_completed(future_map):
            kind, code, fallback_name = future_map[future]
            try:
                if kind == "daily":
                    daily_by_code[code] = future.result()
                else:
                    share_by_code[code] = future.result()
            except Exception as exc:
                if kind == "daily":
                    daily_by_code[code] = []
                else:
                    share_by_code[code] = []
                errors.append(f"{code} {fallback_name}: Tushare {kind} 获取失败：{exc}")

    for group, code, fallback_name in tasks:
        klines = daily_by_code.get(code, [])
        share_rows = share_by_code.get(code, [])
        latest = klines[-1] if klines else {}
        close = latest.get("close")
        row = {
            "group": group,
            "code": code,
            "name": fallback_name,
            "price": close,
            "pct": latest.get("pct"),
            "turnover": latest.get("amount"),
            "main_flow_yi": share_flow_yi(share_rows, close),
            "main_flow_pct": share_change_pct(share_rows),
            "r5": pct_return(klines, 5),
            "r20": pct_return(klines, 20),
            "r60": pct_return(klines, 60),
            "pos60": moving_position(klines, 60),
            "last_kline_date": latest.get("date", "-"),
            "share_date": share_rows[-1].get("date", "-") if share_rows else "-",
        }
        row["state"] = classify(row)
        row["score"] = score(row)
        rows.append(row)
    return rows, errors


def collect_dashboard_data(source, token):
    if source == "eastmoney":
        rows, errors = collect_eastmoney_data()
        return rows, errors, "东方财富行情/K线 + 交易所ETF份额", "资金流使用交易所ETF份额变化 × ETF价格"

    if source == "auto":
        rows, errors = collect_eastmoney_data()
        return rows, errors, "东方财富行情/K线 + 交易所ETF份额", "资金流使用交易所ETF份额变化 × ETF价格"

    rows, errors = collect_tushare_data(token)
    if source == "tushare":
        return rows, errors, "Tushare Pro fund_daily + fund_share", "估算申赎资金流 = 份额变化 × 收盘价"

    return rows, errors, "Tushare Pro fund_daily + fund_share", "估算申赎资金流 = 份额变化 × 收盘价"


def summarize(rows):
    by_group = {}
    for row in rows:
        item = by_group.setdefault(
            row["group"],
            {
                "count": 0,
                "flow": 0.0,
                "flow_count": 0,
                "r5": [],
                "r20": [],
                "r60": [],
                "rel5": [],
                "rel20": [],
                "rel60": [],
                "relative_score": [],
                "strong": 0,
                "weak": 0,
            },
        )
        item["count"] += 1
        if row.get("main_flow_yi") is not None:
            item["flow"] += row["main_flow_yi"]
            item["flow_count"] += 1
        for key in ("r5", "r20", "r60"):
            if row.get(key) is not None:
                item[key].append(row[key])
        for key in ("rel5", "rel20", "rel60", "relative_score"):
            if row.get(key) is not None:
                item[key].append(row[key])
        if (row.get("rel5") or 0) > 0 and (row.get("rel20") or 0) > 0:
            item["strong"] += 1
        if (row.get("rel5") or 0) < 0 and (row.get("rel20") or 0) < 0:
            item["weak"] += 1

    summary = []
    for group, item in by_group.items():
        summary.append(
            {
                "group": group,
                "count": item["count"],
                "flow": item["flow"],
                "flow_count": item["flow_count"],
                "r5": avg(item["r5"]),
                "r20": avg(item["r20"]),
                "r60": avg(item["r60"]),
                "rel5": avg(item["rel5"]),
                "rel20": avg(item["rel20"]),
                "rel60": avg(item["rel60"]),
                "relative_score": avg(item["relative_score"]),
                "strong": item["strong"],
                "weak": item["weak"],
                "score": (avg(item["relative_score"]) or 0) + (max(min(item["flow"], 5), -5) * 0.05 if item["flow_count"] else 0),
            }
        )
    return sorted(summary, key=lambda x: x["score"], reverse=True)


def avg(values):
    if not values:
        return None
    return sum(values) / len(values)


def make_signal_text(summary, rows):
    top_groups = summary[:3]
    weak_groups = list(reversed(summary[-3:]))
    top_rows = sorted(rows, key=lambda x: x["score"], reverse=True)[:8]
    flow_covered = sum(item.get("flow_count", 0) for item in summary)
    flow_total = sum(item.get("count", 0) for item in summary)
    divergence = [
        row
        for row in rows
        if (row.get("main_flow_yi") or 0) > 0 and (row.get("rel5") is not None and row["rel5"] < 0)
    ][:6]

    lines = []
    if top_groups:
        prefix = "资金和相对强弱最靠前" if flow_total and flow_covered / flow_total >= 0.6 else "相对强弱最靠前"
        lines.append(prefix + "：" + "、".join(item["group"] for item in top_groups))
    if flow_total and flow_covered < flow_total:
        lines.append(f"资金流覆盖率：{flow_covered}/{flow_total}，覆盖不足时不要把资金合计当作全市场结论。")
    if weak_groups:
        lines.append("相对偏弱/需回避：" + "、".join(item["group"] for item in weak_groups))
    if top_rows:
        lines.append("ETF观察池：" + "、".join(f'{r["name"]}({r["code"]})' for r in top_rows[:5]))
    if divergence:
        lines.append("异常：有资金流入但5日仍跌，可能是承接、托底或分歧，需要看成分股。")
    return lines


def html_table(headers, rows_html):
    return (
        "<table><thead><tr>"
        + "".join(f"<th>{html.escape(h)}</th>" for h in headers)
        + "</tr></thead><tbody>"
        + "".join(rows_html)
        + "</tbody></table>"
    )


def render_html(rows, errors, source_name, flow_label):
    REPORT_DIR.mkdir(exist_ok=True)
    CACHE_DIR.mkdir(exist_ok=True)
    rows = [row for row in rows if isinstance(row, dict) and row.get("group") and row.get("code") and row.get("name")]
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    benchmark = apply_relative_metrics(rows)
    summary = summarize(rows)
    signals = make_signal_text(summary, rows)
    top_rows = sorted(rows, key=lambda x: x["score"], reverse=True)
    flow_covered = sum(1 for row in rows if row.get("main_flow_yi") is not None)
    flow_total = len(rows)
    net_flow = sum(row.get("main_flow_yi") or 0 for row in rows if row.get("main_flow_yi") is not None)
    up_count = sum(1 for row in rows if (row.get("pct") or 0) > 0)
    down_count = sum(1 for row in rows if (row.get("pct") or 0) < 0)
    strong_count = sum(1 for row in rows if (row.get("relative_score") or 0) > 0)
    top_group = summary[0]["group"] if summary else "-"

    with (CACHE_DIR / "latest_rows.json").open("w", encoding="utf-8") as f:
        json.dump({"updated_at": now, "rows": rows, "errors": errors}, f, ensure_ascii=False, indent=2)

    summary_rows = []
    for item in summary:
        cls = "up" if item["flow_count"] and item["flow"] > 0 else "down" if item["flow_count"] and item["flow"] < 0 else "muted"
        summary_rows.append(
            "<tr>"
            f"<td>{html.escape(item['group'])}</td>"
            f"<td>{item['count']}</td>"
            f"<td class='{cls}'>{format_flow_sum(item['flow'], item['flow_count'], item['count'])}</td>"
            f"<td>{format_pct(item['r5'])}</td>"
            f"<td>{format_pct(item['r20'])}</td>"
            f"<td>{format_pct(item['r60'])}</td>"
            f"<td>{format_pct(item['relative_score'])}</td>"
            f"<td>{item['strong']}</td>"
            f"<td>{item['weak']}</td>"
            "</tr>"
        )

    detail_rows = []
    for rank, row in enumerate(top_rows, start=1):
        flow_cls = "up" if row.get("main_flow_yi") is not None and row["main_flow_yi"] > 0 else "down" if row.get("main_flow_yi") is not None and row["main_flow_yi"] < 0 else "muted"
        pct_cls = "up" if (row.get("pct") or 0) > 0 else "down" if (row.get("pct") or 0) < 0 else ""
        state_text = row["state"]
        state_cls = "state-strong" if "强势" in state_text else "state-risk" if "背离" in state_text or "承压" in state_text else "state-low" if "不足" in state_text else "state-neutral"
        score_cls = "up" if (row.get("relative_score") or 0) > 0 else "down" if (row.get("relative_score") or 0) < 0 else "muted"
        detail_rows.append(
            "<tr>"
            f"<td class='rank-cell'>{rank}</td>"
            f"<td>{html.escape(row['name'])}</td>"
            f"<td><span class='code-tag'>{row['code']}</span></td>"
            f"<td>{format_pct(row['r20'])}</td>"
            f"<td>{format_pct(row['r60'])}</td>"
            f"<td class='{score_cls}'>{format_score_value(row.get('relative_score'))}</td>"
            f"<td><span class='trend-tag'>{trend_marker(row)}</span></td>"
            f"<td>{html.escape(row['group'])}</td>"
            f"<td>{row['price'] if row['price'] is not None else '-'}</td>"
            f"<td class='{pct_cls}'>{format_pct(row['pct'])}</td>"
            f"<td>{format_pct(row['r5'])}</td>"
            f"<td>{format_pct(row['rel5'])}</td>"
            f"<td>{format_pct(row['rel20'])}</td>"
            f"<td>{format_pct(row['rel60'])}</td>"
            f"<td class='{flow_cls}'>{format_yi(row['main_flow_yi'])}</td>"
            f"<td>{format_pct(row['main_flow_pct'])}</td>"
            f"<td>{html.escape(row.get('flow_source') or row.get('scale_source') or '-')}</td>"
            f"<td>{html.escape(str(row.get('scale_date') or '-'))}</td>"
            f"<td>{format_pct(row['pos60'])}</td>"
            f"<td><span class='state-tag {state_cls}'>{html.escape(state_text)}</span></td>"
            f"<td>{format_market_date(row['last_kline_date'])}</td>"
            "</tr>"
        )

    error_html = ""
    if errors:
        error_html = (
            "<section class='warn'><h2>抓取提醒</h2><ul>"
            + "".join(f"<li>{html.escape(e)}</li>" for e in errors[:20])
            + "</ul></section>"
        )

    signal_html = "".join(f"<li>{html.escape(line)}</li>" for line in signals)
    net_flow_cls = "up" if net_flow > 0 else "down" if net_flow < 0 else "muted"
    overview_html = (
        "<div class='overview'>"
        "<div class='metric'>"
        "<span>资金覆盖</span>"
        f"<b>{flow_covered}/{flow_total}</b>"
        f"<small>{flow_covered / flow_total * 100 if flow_total else 0:.0f}% ETF 有资金口径</small>"
        "</div>"
        "<div class='metric'>"
        "<span>样本净流</span>"
        f"<b class='{net_flow_cls}'>{format_yi(net_flow)}</b>"
        "<small>按已覆盖ETF合计</small>"
        "</div>"
        "<div class='metric'>"
        "<span>上涨/下跌</span>"
        f"<b><span class='up'>{up_count}</span><em>/</em><span class='down'>{down_count}</span></b>"
        "<small>按今日涨跌幅统计</small>"
        "</div>"
        "<div class='metric'>"
        "<span>相对占优</span>"
        f"<b>{strong_count}</b>"
        f"<small>当前最强板块：{html.escape(top_group)}</small>"
        "</div>"
        "</div>"
    )
    coverage_html = (
        f"<p class='coverage'>资金流覆盖：{flow_covered}/{flow_total}。"
        "覆盖不足时，板块资金合计只代表已取到资金字段的 ETF，不代表该板块完整净流入。</p>"
        f"<p class='coverage'>相对强弱基准：{BENCHMARK_NAME}({BENCHMARK_CODE})，"
        f"5日 {format_pct(benchmark.get('r5'))}，20日 {format_pct(benchmark.get('r20'))}，60日 {format_pct(benchmark.get('r60'))}。"
        "综合分 = 0.25×相对5日 + 0.45×相对20日 + 0.30×相对60日。</p>"
    )

    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>A股ETF资金观察</title>
  <style>
    :root {{
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #20242a;
      --muted: #667085;
      --line: #d9dee7;
      --up: #c0352b;
      --down: #137a45;
      --accent: #215f9a;
      --accent-soft: #e8f0f8;
      --shadow: 0 10px 24px rgba(16, 24, 40, 0.07);
    }}
    body {{
      margin: 0;
      background: #eef2f6;
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", Arial, sans-serif;
      font-size: 14px;
    }}
    header {{
      background: #ffffff;
      border-bottom: 1px solid var(--line);
      padding: 16px 24px;
      position: sticky;
      top: 0;
      z-index: 4;
      box-shadow: 0 4px 18px rgba(16, 24, 40, 0.05);
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 22px;
      letter-spacing: 0;
    }}
    .head-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }}
    .meta {{ color: var(--muted); }}
    .actions {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .refresh-button {{
      border: 1px solid var(--accent);
      background: var(--accent);
      color: #fff;
      border-radius: 6px;
      padding: 8px 12px;
      font-size: 14px;
      cursor: pointer;
      min-width: 92px;
      transition: background .15s ease, transform .15s ease, box-shadow .15s ease;
      box-shadow: 0 6px 14px rgba(33, 95, 154, 0.18);
    }}
    .refresh-button:hover {{
      background: #174b7e;
      transform: translateY(-1px);
    }}
    .refresh-button:disabled {{
      cursor: wait;
      opacity: 0.68;
      transform: none;
    }}
    .refresh-status {{
      color: var(--muted);
      min-width: 168px;
      text-align: right;
    }}
    main {{ padding: 20px 24px 40px; max-width: 1480px; margin: 0 auto; }}
    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      margin-bottom: 16px;
      padding: 16px;
      box-shadow: var(--shadow);
    }}
    h2 {{
      font-size: 16px;
      margin: 0 0 12px;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    h2::before {{
      content: "";
      width: 4px;
      height: 16px;
      border-radius: 4px;
      background: var(--accent);
    }}
    .overview {{
      display: grid;
      grid-template-columns: repeat(4, minmax(160px, 1fr));
      gap: 12px;
      margin-bottom: 14px;
    }}
    .metric {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcff;
      padding: 12px 14px;
    }}
    .metric span {{
      color: var(--muted);
      display: block;
      margin-bottom: 8px;
      font-size: 13px;
    }}
    .metric b {{
      display: block;
      font-size: 24px;
      line-height: 1.15;
      letter-spacing: 0;
    }}
    .metric em {{
      color: #98a2b3;
      font-style: normal;
      padding: 0 5px;
    }}
    .metric small {{
      display: block;
      color: var(--muted);
      margin-top: 8px;
    }}
    .signals {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 10px;
      padding: 0;
      margin: 0;
      list-style: none;
    }}
    .signals li {{
      border-left: 4px solid var(--accent);
      background: var(--accent-soft);
      padding: 10px 12px;
      border-radius: 4px;
    }}
    .table-wrap {{
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      white-space: nowrap;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 10px 9px;
      text-align: right;
    }}
    th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) {{ text-align: left; }}
    th {{
      color: #344054;
      background: #f4f7fb;
      font-weight: 600;
    }}
    tbody tr:nth-child(even) {{ background: #fbfcfe; }}
    tr:hover {{ background: #eef6ff; }}
    .up {{ color: var(--up); font-weight: 600; }}
    .down {{ color: var(--down); font-weight: 600; }}
    .muted {{ color: var(--muted); }}
    .rank-cell {{
      color: #344054;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
    }}
    .code-tag {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 58px;
      border: 1px solid #d0d7e2;
      border-radius: 6px;
      background: #f7f9fc;
      color: #344054;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      padding: 3px 6px;
    }}
    .state-tag {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 92px;
      border-radius: 999px;
      padding: 4px 9px;
      font-size: 12px;
      line-height: 1.2;
      border: 1px solid transparent;
    }}
    .state-strong {{ background: #fff1f0; border-color: #ffd0cc; color: var(--up); }}
    .state-risk {{ background: #f0f8f3; border-color: #cfe8d8; color: var(--down); }}
    .state-low {{ background: #f2f4f7; border-color: #d0d5dd; color: var(--muted); }}
    .state-neutral {{ background: #eef4fb; border-color: #c9dced; color: var(--accent); }}
    .trend-tag {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 32px;
      height: 28px;
      border-radius: 8px;
      background: #f7f9fc;
      border: 1px solid #d0d7e2;
      font-size: 16px;
      line-height: 1;
    }}
    .date-tag {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 88px;
      border-radius: 6px;
      padding: 3px 7px;
      border: 1px solid #d0d7e2;
      background: #f7f9fc;
      color: #344054;
      font-size: 12px;
    }}
    .date-stale {{
      border-color: #e7c56f;
      background: #fffaf0;
      color: #946200;
    }}
    .date-fresh {{
      border-color: #c9dced;
      background: #eef4fb;
      color: var(--accent);
    }}
    .note, .warn {{ color: var(--muted); }}
    .coverage {{
      margin: 12px 0 0;
      color: var(--muted);
    }}
    .warn {{ border-color: #e7c56f; background: #fffaf0; box-shadow: none; }}
    .rules {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 12px;
    }}
    .rule {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px;
      background: #fbfcfe;
    }}
    .rule b {{ display: block; margin-bottom: 6px; }}
    @media (max-width: 760px) {{
      .head-row {{ align-items: flex-start; flex-direction: column; }}
      .actions {{ justify-content: flex-start; }}
      .refresh-status {{ text-align: left; }}
      .overview {{ grid-template-columns: 1fr 1fr; }}
    }}
    @media (max-width: 520px) {{
      main {{ padding: 14px 12px 32px; }}
      header {{ padding: 14px 12px; }}
      .overview {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="head-row">
      <div>
        <h1>A股ETF资金观察</h1>
        <div class="meta">生成时间：{html.escape(now)} ｜ 数据源：{html.escape(source_name)} ｜ 口径：{html.escape(flow_label)}</div>
      </div>
      <div class="actions">
        <button class="refresh-button" id="refreshButton" type="button">刷新数据</button>
        <span class="refresh-status" id="refreshStatus"></span>
      </div>
    </div>
  </header>
  <main>
    <section>
      <h2>今日快速判断</h2>
      {overview_html}
      <ul class="signals">{signal_html}</ul>
      {coverage_html}
    </section>

    <section>
      <h2>板块资金与多周期强弱</h2>
      <div class="table-wrap">
        {html_table(["分组", "ETF数量", "资金流合计", "平均5日", "平均20日", "平均60日", "平均相对分", "相对5/20强", "相对5/20弱"], summary_rows)}
      </div>
    </section>

    <section>
      <h2>ETF明细排序</h2>
      <div class="table-wrap">
        {html_table(["排名", "板块", "代码", "20日涨幅", "60日涨幅", "得分", "趋势", "分组", "价格", "今日涨跌", "5日", "相对5日", "相对20日", "相对60日", "资金流", "份额/主力占比", "资金来源", "份额日期", "60日位置", "状态", "行情日期"], detail_rows)}
      </div>
    </section>

    <section>
      <h2>使用规则</h2>
      <div class="rules">
        <div class="rule"><b>主线候选</b>相对20日和相对60日为正，说明不只是上涨，而是在跑赢基准。</div>
        <div class="rule"><b>强势回调</b>相对5日转弱但相对20/60日仍强，先看承接，不急着判定趋势结束。</div>
        <div class="rule"><b>超跌反弹</b>相对5日强但相对20/60日弱，按短线修复看，不直接当主线。</div>
        <div class="rule"><b>防追高</b>相对分很高但60日位置接近高位，容易变成高成本接力。</div>
      </div>
    </section>

    <section class="note">
      <h2>口径说明</h2>
      <p>资金流优先使用交易所ETF份额变化乘以ETF价格估算：上交所可直接取最近两期份额，深交所当前接口只给最新份额，第一次运行会缓存，第二次运行后可用缓存差值计算。若交易所份额或价格缺失，则保留 Tushare/东方财富字段；仍缺失时显示“缺失”。</p>
    </section>
    {error_html}
  </main>
  <script>
    const refreshButton = document.getElementById("refreshButton");
    const refreshStatus = document.getElementById("refreshStatus");

    refreshButton.addEventListener("click", async () => {{
      if (!["127.0.0.1", "localhost"].includes(window.location.hostname)) {{
        refreshStatus.textContent = "线上版由 GitHub Actions 自动刷新";
        return;
      }}
      refreshButton.disabled = true;
      refreshButton.textContent = "刷新中";
      refreshStatus.textContent = "正在重新抓取数据...";
      try {{
        const response = await fetch("/refresh", {{ method: "POST" }});
        const result = await response.json();
        if (!response.ok || !result.ok) {{
          throw new Error(result.error || "刷新失败");
        }}
        refreshStatus.textContent = "刷新完成，正在更新页面";
        window.location.reload();
      }} catch (error) {{
        refreshStatus.textContent = error.message || "刷新失败，请稍后再试";
        refreshButton.disabled = false;
        refreshButton.textContent = "刷新数据";
      }}
    }});

    if (!["127.0.0.1", "localhost"].includes(window.location.hostname)) {{
      refreshButton.textContent = "自动刷新";
      refreshStatus.textContent = "线上版由 GitHub Actions 更新";
    }}
  </script>
</body>
</html>
"""
    HTML_PATH.write_text(page, encoding="utf-8")
    return HTML_PATH


def generate_dashboard(source, token):
    rows, errors, source_name, flow_label = collect_dashboard_data(source, token)
    scale_errors = apply_exchange_scale_flows(rows)
    errors.extend(scale_errors)
    if any("已用交易所ETF份额变化计算资金流" in item for item in scale_errors):
        flow_label = "优先使用交易所ETF份额变化 × ETF价格；缺失时保留原资金字段"
    return render_html(rows, errors, source_name, flow_label)


def make_report_handler(source, token):
    class ReportHandler(SimpleHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/refresh":
                self.send_error(404, "Not found")
                return
            try:
                path = generate_dashboard(source, token)
                payload = {"ok": True, "path": str(path)}
                status = 200
            except Exception as exc:
                payload = {"ok": False, "error": str(exc)}
                status = 500
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ReportHandler


def serve_report(port, source, token):
    os.chdir(str(ROOT))
    handler = make_report_handler(source, token)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"网页已生成：{HTML_PATH}")
    print(f"本地访问：http://127.0.0.1:{port}/reports/etf_dashboard.html")
    print("按 Ctrl+C 停止。")
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description="生成A股ETF资金观察网页")
    parser.add_argument("--serve", action="store_true", help="生成后启动本地网页服务")
    parser.add_argument("--port", type=int, default=8765, help="本地网页端口，默认8765")
    parser.add_argument("--source", choices=["auto", "tushare", "eastmoney"], default="auto", help="数据源，默认auto优先Tushare")
    parser.add_argument("--token", default="", help="Tushare token，也可以放到环境变量TUSHARE_TOKEN或config/tushare_token.txt")
    args = parser.parse_args()

    try:
        token = load_tushare_token(args.token)
        path = generate_dashboard(args.source, token)
    except Exception as exc:
        print(f"数据抓取失败：{exc}", file=sys.stderr)
        print("请检查网络，或稍后再试。", file=sys.stderr)
        return 1

    print(f"已生成：{path}")
    if args.serve:
        serve_report(args.port, args.source, token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
