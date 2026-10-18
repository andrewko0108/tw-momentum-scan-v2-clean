#!/usr/bin/env python3
"""Taiwan momentum scanner v2. Independent GitHub Actions project.
Run: python screener.py --output output [--csv path --sectors path --as-of YYYY-MM-DD]
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
from datetime import datetime,date,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import data_sources as ds
from engine import TRACKING_START,run_replay
from etf_data import fetch_holdings,load_csv
from reports import write_all

TZ=ZoneInfo('Asia/Taipei')


def resolve_market(rows, industry_map):
    """Restrict to ordinary four-digit TWSE/TPEx companies listed in official registries.
    Combined archived CSV has no market; resolve by unique official company directory membership.
    """
    codes=defaultdict(set)
    for market,code in industry_map:codes[code].add(market)
    resolved={}
    for code,arr in rows.items():
        markets=codes.get(code,set())
        if len(markets)!=1:continue
        market=next(iter(markets))
        valid=[]
        for bar in arr:
            if bar['market'] not in ('歷史來源',market):continue
            valid.append(dict(bar,market=market))
        if valid: resolved[code]=valid
    return resolved


def validate_tracking_sessions(prices, market_dates, start, as_of, strict):
    dates=[d for d in market_dates if start<=d<=as_of]
    if not dates:return
    # Check broad market coverage for EVERY tracked day; refuse the illusion
    # of complete screening if a partial archive silently drops a board.
    bydate=defaultdict(lambda:Counter())
    for bars in prices.values():
        for r in bars:
            if r['date'] in dates: bydate[r['date']][r['market']]+=1
    bad=[]
    for day in dates:
        counts=bydate[day]
        if strict and (counts['上市']<500 or counts['上櫃']<350):
            bad.append((day,dict(counts)))
    if bad:
        raise RuntimeError(f'Incomplete daily market archive sessions: {bad[:5]}; do not publish misleading watchlist')


def cli():
    p=argparse.ArgumentParser(description='TWSE/TPEx momentum screening + tracking since defined start')
    p.add_argument('--output',default='output')
    p.add_argument('--cache',default='data/archive')
    p.add_argument('--csv',help='Offline OHLCV CSV (date,code,name,volume,open,high,low,close)')
    p.add_argument('--sectors',help='Offline official-company registry CSV (market,code,industry)')
    p.add_argument('--etf-csv',help='Optional verified ETF holdings changes CSV')
    p.add_argument('--as-of',help='Run historical/offline day; live mode must be most recent session')
    p.add_argument('--start',default=TRACKING_START,help='First possible entry YYYY-MM-DD')
    p.add_argument('--allow-stale',action='store_true',help='Manual report for last prior session, NOT daily schedule')
    return p.parse_args()


def main():
    args=cli()
    today=datetime.now(TZ).date().isoformat()
    if args.as_of: date.fromisoformat(args.as_of)
    start=date.fromisoformat(args.start).isoformat()
    if not args.csv and not args.as_of and datetime.now(TZ).weekday()>=5:
        print('SKIP: weekend/non-trading day; no report sent.',flush=True);return
    history=ds.History()
    if args.csv:
        if not args.as_of:raise ValueError('Offline CSV mode requires --as-of YYYY-MM-DD')
        as_of=args.as_of
        n=ds.scan_csv(history,Path(args.csv),as_of)
        if n<100:print('Warning: small offline fixture; results are NOT full-market',flush=True)
        s=ds.session()
        industry=ds.industry_map_from_csv(args.sectors) if args.sectors else None
        if industry is None:raise ValueError('Offline --csv requires --sectors to identify TWSE/TPEx ordinary stocks')
        official_day=as_of
        origin='Offline CSV supplied by user, NOT real-time market completeness verified'
    else:
        s,twse,tpex,official_day=ds.fetch_official_latest_pair()
        if not args.as_of and official_day!=today:
            # Both latest-only OpenAPIs can lag together. Attempt exact-date
            # quote endpoints before assuming the exchange is closed.
            print(f'Latest-only endpoints report {official_day}; checking dated market data {today}',flush=True)
            listed=ds.historical_twse(s,today)
            if len(listed)>=100:
                otc=ds.historical_tpex(s,today)
                if len(otc)<100:
                    raise RuntimeError(f'{today}: TWSE available but TPEx incomplete; refuse partial screen')
                twse,tpex,official_day=listed,otc,today
            else:
                print(f'SKIP: no TWSE dated quotes for {today}; holiday/data unpublished. No stale alert.',flush=True)
                return
        if args.as_of and args.as_of!=official_day:
            raise RuntimeError('Live mode --as-of must equal aligned official latest date; use --csv for historical replay')
        if official_day<start:
            print(f'SKIP: official date {official_day} before new strategy start {start}',flush=True);return
        as_of=official_day
        ds.download_archives(history,Path(args.cache),as_of,start_year=max(2004,int(start[:4])-1))
        ds.backfill_recent_from_official(history,s,None,official_day,twse,tpex)
        industry=ds.industry_map_from_official(s)
        origin='TWSE + TPEx official daily quote API (latest), dated after-trading API (patch), public community historical ZIP archive'
    resolved=resolve_market(history.bars,industry)
    if not resolved:raise RuntimeError('No correctly mapped TWSE/TPEx stocks')
    market_dates=sorted(d for d in history.all_market_dates if d<=as_of)
    if market_dates[-1]!=as_of:raise RuntimeError(f'No prices for target {as_of}')
    validate_tracking_sessions(resolved,market_dates,start,as_of,strict=not bool(args.csv))
    if args.etf_csv:
        etf,etf_info=load_csv(args.etf_csv)
    else:
        etf,etf_info=fetch_holdings(start,as_of)
    result=run_replay(resolved,market_dates,as_of,etf,etf_info['status'],start,etf_complete_days=set(etf_info.get('complete_days',[])))
    info={'source_date':as_of,'start':start,'sources':origin,
          'etf':etf_info,'universe_count':len(resolved),
          'raw_records_loaded':history.rows_loaded,'price_basis':'unadjusted exchange OHLCV',
          'coverage':'full-market coverage checks passed' if not args.csv else 'offline sample; NOT verified full market',
          'execution':today}
    if not result['latest']:
        print(f'No tracked market dates since {start}; nothing to publish.',flush=True);return
    write_all(args.output,result,info)
    print(f'As-of {as_of}: {len(resolved)} symbols; '
          f'watchlist {len(result["watchlist"])}, added {len(result["added"])}, '
          f'removed {len(result["removed"])}, continuous {len(result["continuous"])}; '
          f'ETF {etf_info["status"]}; saved {args.output}',flush=True)


if __name__=='__main__':
    main()
