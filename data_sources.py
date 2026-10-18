#!/usr/bin/env python3
"""台股上市/上櫃電子與設備股動能訊號＋追蹤報酬掃描器 v1.5.1 (2026)
使用歸檔歷史日線 + 官方行情 + 官方公司產業代碼；判斷規則見 README.md。
依賴: pandas, requests。歷史資料源為第三方公開 GitHub 壓縮檔（源於 TWSE/TPEx）。
"""
from __future__ import annotations

import argparse
import csv
import io
import html
import json
import os
import re
import sys
import time
import warnings
import zipfile
from collections import defaultdict, deque
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

REPO = "yukishirotsubasa/tw-stock-data-release"
RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/tags/daily-close-csv"
TWSE_API = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_API = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
TWSE_PROFILE_API = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_PROFILE_API = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
# Industry codes are retained only for descriptive labels in the source registry.
# IMPORTANT: v2 does NOT limit the scan to electronics or any industry.
INDUSTRY_NAMES = {
    "05": "電機機械", "24": "半導體", "25": "電腦及週邊設備", "26": "光電",
    "27": "通信網路", "28": "電子零組件", "29": "電子通路", "30": "資訊服務",
    "31": "其他電子", "36": "數位雲端",
}
CODE = re.compile(r"^[1-9][0-9]{3}$")
EXCLUDED_SUFFIX = ("DR", "R1", "R2", "特")
# Preserve sufficient pre-start daily OHLCV for 120-day SMA + Wilder RSI.
TRACKING_START = "2026-10-19"
PRESTART_BARS = 200
TZ_TAIPEI = ZoneInfo("Asia/Taipei")


def session():
    s = requests.Session()
    r = Retry(total=3, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504),
              allowed_methods=("GET",))
    s.mount("https://", HTTPAdapter(max_retries=r))
    s.headers.update({"User-Agent": "TaiwanMomentumScreener/1.0 (+educational use)",
                      "Accept": "application/json, */*"})
    return s



class TemporarySourceError(RuntimeError):
    """A data source did not deliver one COMPLETE, parseable JSON response."""


def fetch_json_reliably(s, url, *, params=None, timeout=55, label="資料來源", attempts=4):
    """Retry a WHOLE JSON response, including mid-body ChunkedEncodingError.

    An HTTPAdapter retry alone cannot recover a transfer that dies while
    requests reads the response body. We retry the idempotent GET from the
    beginning; an incomplete JSON body is NEVER treated as a partial quote.
    Fatal HTTP 4xx errors (except 408/429) are reported immediately.
    """
    last = None
    for attempt in range(1, attempts + 1):
        try:
            # Close the response even when parsing/reading raises mid-stream.
            with s.get(url, params=params, timeout=timeout, stream=True,
                       headers={"Connection": "close", "Cache-Control": "no-cache"}) as response:
                response.raise_for_status()
                # .json() reads the ENTIRE response body. Body truncation can
                # raise ChunkedEncodingError *here*, not at HTTP connect time.
                return response.json()
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status not in (408, 429, 500, 502, 503, 504):
                raise RuntimeError(f"{label}: HTTP {status}; API may have changed") from exc
            last = exc
        except (requests.exceptions.RequestException, ValueError) as exc:
            # ValueError includes JSONDecodeError from incomplete/malformed JSON.
            last = exc
        if attempt < attempts:
            wait = min(2 ** (attempt - 1), 6)
            print(f"[RETRY {attempt}/{attempts}] {label}: {type(last).__name__}: "
                  f"{str(last)[:160]}; {wait}s later", flush=True)
            time.sleep(wait)
    raise TemporarySourceError(
        f"{label}: failed {attempts} complete JSON fetches "
        f"({type(last).__name__}: {str(last)[:220]})") from last

def usable_stock(code, name):
    """Only numeric, 4-digit ordinary shares; removes DR and explicitly named preferred shares."""
    return bool(CODE.fullmatch(str(code).strip())) and not str(name).strip().endswith(EXCLUDED_SUFFIX)


def num(x):
    try:
        s = str(x).strip().replace(",", "")
        if s in ("", "--", "---", "-", "None", "nan"):
            return None
        v = float(s)
        return v if pd.notna(v) else None
    except (ValueError, TypeError):
        return None


def iso_date(raw):
    s = str(raw).strip().replace("/", "").replace("-", "")
    if len(s) == 8 and s[:4].isdigit() and int(s[:4]) >= 1900:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    if len(s) == 7 and s.isdigit():
        return f"{int(s[:3]) + 1911:04d}-{s[3:5]}-{s[5:7]}"
    raise ValueError(f"Invalid date: {raw!r}")


def normalize(r, market="歷史來源"):
    """Accept upstream daily CSV or official TWSE/TPEx latest JSON."""
    if "code" in r:
        d, code, name = r.get("date"), r.get("code"), r.get("name", "")
        vol, op, hi, lo, cl = (r.get(x) for x in ("volume", "open", "high", "low", "close"))
    elif "Code" in r:
        d, code, name = r.get("Date"), r.get("Code"), r.get("Name", "")
        vol, op, hi, lo, cl = (r.get(x) for x in ("TradeVolume", "OpeningPrice", "HighestPrice", "LowestPrice", "ClosingPrice"))
    else:
        d, code, name = r.get("Date"), r.get("SecuritiesCompanyCode"), r.get("CompanyName", "")
        vol, op, hi, lo, cl = (r.get(x) for x in ("TradingShares", "Open", "High", "Low", "Close"))
    code, name = str(code).strip(), str(name).strip()
    if not usable_stock(code, name):
        return None
    try:
        d = iso_date(d)
    except ValueError:
        return None
    vals = [num(x) for x in (vol, op, hi, lo, cl)]
    if any(v is None for v in vals):
        return None
    v, o, h, l, c = vals
    if v <= 0 or min(o, h, l, c) <= 0 or h < max(o, c, l) or l > min(o, c):
        return None
    return {"date": d, "code": code, "name": name, "volume": v,
            "open": o, "high": h, "low": l, "close": c, "market": market}


class History:
    def __init__(self):
        self.bars = defaultdict(lambda: deque(maxlen=PRESTART_BARS))
        self.max_high = {}
        self.first_date = {}
        self.all_market_dates = set()
        self.rows_loaded = 0

    def insert(self, row):
        code, day = row["code"], row["date"]
        arr = self.bars[code]
        if day >= TRACKING_START and arr.maxlen is not None:
            # GitHub runner files are ephemeral; reconstruct complete tracking
            # history since 2026-10-08, without relying on cache/artifact state.
            arr = deque(arr)
            self.bars[code] = arr
        if arr and day < arr[-1]["date"]:
            raise ValueError(f"Data out of chronological order for {code}: {day}")
        if arr and day == arr[-1]["date"]:
            # Same-day official snapshot is authoritative over the community archive.
            prev_high = arr[-1]["prior_high"]
            arr.pop()
        else:
            prev_high = self.max_high.get(code)
        row = dict(row, prior_high=prev_high)
        arr.append(row)
        self.max_high[code] = max(float(prev_high or 0), row["high"])
        self.first_date.setdefault(code, day)
        self.all_market_dates.add(day)
        self.rows_loaded += 1


def scan_archive_zip(history, path, as_of, year=None):
    """Read both the source's merged yearly_YYYY.csv / weekly_YYYY_Www.csv
    and legacy per-day YYYYMMDD.csv ZIP contents.

    The upstream packager merges all daily CSVs into ONE CSV before zipping;
    checking only YYYYMMDD.csv member names silently discards all history.
    """
    n = 0
    upper = date.fromisoformat(as_of)
    with zipfile.ZipFile(path) as zf:
        members = [x for x in zf.namelist() if x.lower().endswith('.csv') and not x.endswith('/')]
        if not members:
            raise RuntimeError(f"{path.name}: ZIP contains no CSV files")
        # Common source format has exactly one chronological, date-sorted CSV.
        for member in sorted(members):
            m = re.search(r"(20\d{2}[-]?\d{2}[-]?\d{2})\.csv$", member)
            fallback = iso_date(m.group(1)) if m else None
            with zf.open(member) as f:
                stream = io.TextIOWrapper(f, encoding='utf-8-sig', errors='replace', newline='')
                reader = csv.DictReader(stream)
                if not reader.fieldnames or 'code' not in reader.fieldnames:
                    raise RuntimeError(f"{path.name}/{member}: missing 'code' column; found {reader.fieldnames}")
                if 'date' not in reader.fieldnames and fallback is None:
                    raise RuntimeError(f"{path.name}/{member}: merged CSV is missing the 'date' column")
                for r in reader:
                    if not r or not r.get('code'):
                        continue
                    if not r.get('date') and fallback is not None:
                        r['date'] = fallback
                    item = normalize(r)
                    if item is None:
                        continue
                    d = date.fromisoformat(item['date'])
                    # ISO weeks around New Year overlap adjacent calendar years;
                    # insert only the calendar year currently being loaded.
                    if year is not None and d.year != year:
                        continue
                    if d <= upper:
                        history.insert(item)
                        n += 1
    return n


def weeks_intersecting_year(assets, year, upper):
    """Find released ISO-week ZIPs overlapping the specified calendar year."""
    result = []
    begin = date(year, 1, 1)
    end = min(date(year, 12, 31), date.fromisoformat(upper))
    if end < begin:
        return result
    for name in assets:
        m = re.fullmatch(r"weekly_(\d{4})_W(\d{2})\.zip", name)
        if not m:
            continue
        try:
            monday = date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            continue
        if monday <= end and monday + timedelta(days=6) >= begin:
            result.append((monday, name))
    return [name for _, name in sorted(result)]


def scan_csv(history, path, as_of):
    # CSV mode supports a file with many stocks/dates or a directory of YYYYMMDD.csvs.
    paths = sorted(path.glob("**/*.csv")) if path.is_dir() else [path]
    rows = []
    for p in paths:
        with p.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for r in reader:
                if "date" not in r and re.search(r"\d{8}", p.stem):
                    r["date"] = re.search(r"\d{8}", p.stem).group()
                item = normalize(r)
                if item and item["date"] <= as_of:
                    rows.append(item)
    for r in sorted(rows, key=lambda x: (x["date"], x["code"])):
        history.insert(r)
    return len(rows)


def download_archives(history, cache_dir, as_of, start_year, force_current=True, archive_end=None):
    cache_dir.mkdir(parents=True, exist_ok=True)
    s = session()
    payload = fetch_json_reliably(s, RELEASE_API, timeout=45, label="GitHub historical releases")
    assets = {x['name']: x['browser_download_url'] for x in payload.get('assets', [])}
    if not assets:
        raise RuntimeError('GitHub Release has no assets. Check release and permissions.')

    upper = archive_end or as_of
    end_year = int(as_of[:4])
    missing_years = []
    count = 0
    for year in range(start_year, end_year + 1):
        annual = f'yearly_{year}.zip'
        if annual in assets:
            filenames = [annual]
        else:
            filenames = weeks_intersecting_year(assets, year, upper)
        if not filenames:
            missing_years.append(year)
            continue
        year_rows = 0
        for name in filenames:
            file = cache_dir / name
            # An annual archive is fixed after that calendar year. Weekly files
            # are also fixed once their release has settled; refetch active
            # current weeks so corrections can be picked up.
            refresh = (force_current and year == end_year and
                       (name == annual or name == filenames[-1]))
            if not file.exists() or refresh:
                print(f'Downloading {name}...', flush=True)
                with s.get(assets[name], timeout=180, stream=True) as r:
                    r.raise_for_status()
                    temp = file.with_suffix('.zip.part')
                    with temp.open('wb') as out:
                        for chunk in r.iter_content(chunk_size=1024 * 256):
                            if chunk:
                                out.write(chunk)
                    if not zipfile.is_zipfile(temp):
                        temp.unlink(missing_ok=True)
                        raise ValueError(f'Broken archive: {name}')
                    temp.replace(file)
            rows = scan_archive_zip(history, file, upper, year=year)
            # A particular weekly archive can contain ONLY days after the
            # official backfill cutoff. Zero records in that case is expected.
            if name == annual and rows == 0:
                raise RuntimeError(f'{name}: 0 valid stock-date records after parsing; check CSV schema')
            year_rows += rows
            count += rows
        if year_rows == 0:
            # Current-year weekly releases can be all newer than the cutoff
            # only for extremely early January; ordinarily this is a bug.
            raise RuntimeError(f'{year}: 0 valid stock-date records; check weekly archives and CSV schema')
        print(f'  {year}: {year_rows:,} rows ({len(filenames)} archives); total {count:,}', flush=True)
    if missing_years:
        warnings.warn(f'Historical years missing from release: {missing_years}. ATH is not verifiable if history is incomplete.')
    if end_year in missing_years:
        raise RuntimeError('Current-year historical archive missing (no annual or weekly ZIPs); refuse incomplete screening.')
    if count == 0:
        raise RuntimeError('No OHLCV history was parsed; refuse incomplete screening.')
    return count, missing_years


def official_snapshot(s, url, market):
    raw = fetch_json_reliably(s, url, timeout=55, label=f"{market} latest quote OpenAPI")
    if not isinstance(raw, list) or not raw:
        raise RuntimeError(f"{market} endpoint returned no list")
    rows = [normalize(r, market) for r in raw]
    rows = [r for r in rows if r is not None]
    if len(rows) < 100:
        raise RuntimeError(f"{market}: too few valid stock rows ({len(rows)}): schema may have changed")
    dates = {r["date"] for r in rows}
    if len(dates) != 1:
        raise RuntimeError(f"{market}: multiple dates: {dates}")
    return rows, dates.pop()


def fetch_official_latest_pair():
    """Get aligned latest sessions; OpenAPI TWSE may lag the market close."""
    s = session()
    twse, a = official_snapshot(s, TWSE_API, "上市")
    try:
        tpex, b = official_snapshot(s, TPEX_API, "上櫃")
    except TemporarySourceError as exc:
        # Only fall back for transient/partial-download problems; a fully
        # returned but invalid market snapshot must still fail validation.
        # The dated endpoint must independently assert its actual trade date.
        print(f"[FALLBACK] TPEx OpenAPI transport unavailable: {exc}", flush=True)
        tpex = historical_tpex(s, a)
        b = a
        if len(tpex) < 100:
            raise RuntimeError(f"TPEx dated dailyQuotes {a}: insufficient quotes ({len(tpex)}); "
                               "refuse partial watchlist")
        print(f"[FALLBACK OK] TPEx official dated dailyQuotes {b}: {len(tpex)} stocks", flush=True)
    if a < b:
        # TWSE's latest-only OpenAPI can publish later than its dated MI_INDEX.
        twse = historical_twse(s, b)
        if len(twse) < 100:
            raise RuntimeError(f"TWSE OpenAPI is still at {a}; dated MI_INDEX for {b} has only {len(twse)} stocks")
        a = b
        print(f"TWSE latest OpenAPI lag detected; switched to dated MI_INDEX {a}", flush=True)
    elif b < a:
        tpex = historical_tpex(s, a)
        if len(tpex) < 100:
            raise RuntimeError(f"TPEx OpenAPI is still at {b}; dated dailyQuotes for {a} has only {len(tpex)} stocks")
        b = a
        print(f"TPEx latest OpenAPI lag detected; switched to dated dailyQuotes {b}", flush=True)
    if a != b:
        raise RuntimeError(f"Official dates do not match: TWSE {a} vs TPEx {b}")
    return s, twse, tpex, a


def historical_twse(s, day):
    """Official exchange-wide daily OHLCV by date, NOT the latest-only OpenAPI."""
    url = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
    data = fetch_json_reliably(
        s, url, params={"response": "json", "date": day.replace("-", ""),
                        "type": "ALLBUT0999"}, timeout=55,
        label=f"TWSE historical {day}")
    if not isinstance(data, dict):
        raise RuntimeError(f"TWSE {day}: historical response was not an object")
    if data.get("stat") == "OK":
        source_date = data.get("date")
        if not source_date or iso_date(source_date) != day:
            raise RuntimeError(f"TWSE {day}: source date mismatch (returned {source_date!r})")
    tables = data.get("tables", [])
    if not tables:
        tables = [{"fields": data.get(f"fields{i}", []), "data": data.get(f"data{i}", [])} for i in range(1, 15)]
    found = False
    result = []
    for table in tables:
        fields = [str(f).strip() for f in table.get("fields", [])]
        required = ["證券代號", "證券名稱", "成交股數", "開盤價", "最高價", "最低價", "收盤價"]
        if not all(k in fields for k in required):
            continue
        found = True
        ids = {k: fields.index(k) for k in required}
        for cols in table.get("data", []):
            if not isinstance(cols, list) or len(cols) <= max(ids.values()):
                continue
            item = normalize({"date": day, "code": cols[ids["證券代號"]],
                              "name": cols[ids["證券名稱"]], "volume": cols[ids["成交股數"]],
                              "open": cols[ids["開盤價"]], "high": cols[ids["最高價"]],
                              "low": cols[ids["最低價"]], "close": cols[ids["收盤價"]]}, "上市")
            if item:
                result.append(item)
    if not found and str(data.get("stat", "")).lower() not in ("no data", "很抱歉，沒有符合條件的資料!", "查無資料"):
        raise RuntimeError(f"TWSE {day}: no matching table; schema drift or missing dataset")
    return result


def historical_tpex(s, day):
    """TPEx official dated dailyQuotes: tables/fields/data (NOT legacy aaData).

    Validate source date and identify columns by their Chinese labels to avoid
    treating the average PRICE column as trading VOLUME.
    """
    url = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"
    payload = fetch_json_reliably(
        s, url, params={"response": "json", "date": day.replace("-", "/")},
        timeout=55, label=f"TPEx historical {day}")
    if not isinstance(payload, dict):
        raise RuntimeError(f"TPEx {day}: JSON payload was not an object")
    raw_date = payload.get("date") or payload.get("reportDate")
    if not raw_date:
        raise RuntimeError(f"TPEx {day}: response lacks a source date; refuse unverifiable data")
    try:
        observed_date = iso_date(raw_date)
    except (ValueError, TypeError) as e:
        raise RuntimeError(f"TPEx {day}: invalid source date {raw_date!r}") from e
    if observed_date != day:
        raise RuntimeError(f"TPEx {day}: source date mismatch (returned {observed_date})")
    tables = payload.get("tables") or []
    if not isinstance(tables, list):
        raise RuntimeError(f"TPEx {day}: tables is not a list")
    result = []
    found = False
    for table in tables:
        if not isinstance(table, dict):
            continue
        fields = [str(f).strip().replace(" ", "") for f in table.get("fields", [])]
        aliases = {
            "code": ("代號", "證券代號"), "name": ("名稱", "證券名稱"),
            "close": ("收盤", "收盤價"), "open": ("開盤", "開盤價"),
            "high": ("最高", "最高價"), "low": ("最低", "最低價"),
            "volume": ("成交股數", "成交股數(股)", "成交股數（股）"),
        }
        ix = {}
        for k, labels in aliases.items():
            ix[k] = next((fields.index(label) for label in labels if label in fields), None)
        if any(i is None for i in ix.values()):
            continue
        found = True
        for cols in table.get("data", []):
            if not isinstance(cols, (list, tuple)) or len(cols) <= max(ix.values()):
                continue
            row = {"date": day, **{k: cols[i] for k, i in ix.items()}}
            item = normalize(row, "上櫃")
            if item:
                result.append(item)
    if not found:
        raise RuntimeError(f"TPEx {day}: no complete OHLCV table (keys={list(payload.keys())})")
    if len(result) < 100:
        raise RuntimeError(f"TPEx {day}: only {len(result)} valid common stocks; possible incomplete payload")
    return result


def backfill_recent_from_official(history, s, archive_cutoff, latest, twse_latest, tpex_latest):
    """Fill only sessions absent from the archive, then replace the latest
    day's archived data with official exchange snapshots.

    All available release weekly ZIPs are loaded first. In particular, on
    weekends a freshly published week already contains Friday's quotes: do
    NOT re-request its already archived weekday dates from fragile old APIs.
    """
    if not history.all_market_dates:
        raise RuntimeError("No historical trading dates to backfill from")
    last_archive_day = max(history.all_market_dates)
    last = date.fromisoformat(latest)
    if date.fromisoformat(last_archive_day) > last:
        raise RuntimeError(f"Archive day {last_archive_day} newer than official latest {latest}; dates differ")
    if (last - date.fromisoformat(last_archive_day)).days > 14:
        raise RuntimeError(f"Archive is too old ({last_archive_day}) to safely patch to {latest}; verify data provider")
    day = date.fromisoformat(last_archive_day) + timedelta(days=1)
    filled = []
    while day < last:
        if day.weekday() < 5:
            d = day.isoformat()
            a = historical_twse(s, d)
            # No listed market data => no trading session; do not need a TPEX
            # historical request. If TWSE has quote data, both markets must.
            if a:
                b = historical_tpex(s, d)
                if len(a) < 100 or len(b) < 100:
                    raise RuntimeError(f"Incomplete official historical data for {d}: TWSE={len(a)} TPEx={len(b)}")
                for item in sorted(a + b, key=lambda x: x["code"]):
                    history.insert(item)
                filled.append(d)
        day += timedelta(days=1)
    if len(twse_latest) < 100 or len(tpex_latest) < 100:
        raise RuntimeError("Incomplete latest official snapshot; refuse partial screen")
    for item in sorted(twse_latest + tpex_latest, key=lambda x: x["code"]):
        history.insert(item)
    print(f"Official patched sessions: {filled + [latest]}", flush=True)
    return latest


def parse_industry_row(row, market):
    """Return ((market, code), (industry_code, industry_label)), or None.

    TWSE company directory uses Chinese keys, TPEx directory English keys.
    Never infer industry from price-action or the stock's name.
    """
    if not isinstance(row, dict):
        return None
    if market == "上市":
        code = str(row.get("公司代號", "")).strip()
        industry = str(row.get("產業別", "")).strip()
    else:
        code = str(row.get("SecuritiesCompanyCode", "")).strip()
        industry = str(row.get("SecuritiesIndustryCode", "")).strip()
    if not CODE.fullmatch(code):
        return None
    if industry.isdigit():
        industry_code = industry.zfill(2)
    else:
        # Unrecognized descriptions must not be treated as eligible.
        return None
    return (market, code), (industry_code, INDUSTRY_NAMES.get(industry_code, f"其他產業({industry_code})"))


def industry_map_from_official(session_obj):
    """Fetch BOTH official company directories; refuse incomplete/unavailable data."""
    output = {}
    for market, url in (("上市", TWSE_PROFILE_API), ("上櫃", TPEX_PROFILE_API)):
        raw = fetch_json_reliably(
            session_obj, url, timeout=65, label=f"{market} company directory")
        if not isinstance(raw, list) or len(raw) < 100:
            raise RuntimeError(f"{market}: official company profile data missing/incomplete")
        parsed = dict(filter(None, (parse_industry_row(r, market) for r in raw)))
        if len(parsed) < 100 or len(parsed) < len(raw) * 0.6:
            raise RuntimeError(f"{market}: industry code parse insufficient ({len(parsed)}/{len(raw)}); schema changed?")
        output.update(parsed)
        print(f"Industry directory {market}: {len(parsed):,} 4-digit symbols", flush=True)
    return output


def industry_map_from_csv(path):
    """Offline testing option: CSV with 'market,code,industry' columns."""
    industry_map = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        expected = {"market", "code", "industry"}
        if not reader.fieldnames or not expected.issubset(reader.fieldnames):
            raise ValueError(f"Industry CSV must contain {', '.join(sorted(expected))}")
        for r in reader:
            m = str(r["market"]).strip()
            c = str(r["code"]).strip()
            ind = str(r["industry"]).strip()
            if m not in ("上市", "上櫃"):
                raise ValueError(f"Invalid market {m!r} in industry CSV")
            result = parse_industry_row({"公司代號": c, "產業別": ind}, "上市")
            if result is None:
                raise ValueError(f"Invalid industry CSV code/industry: {c!r}, {ind!r}")
            industry_map[(m,c)] = result[1]
    if not industry_map:
        raise ValueError("Industry CSV is empty")
    return industry_map


