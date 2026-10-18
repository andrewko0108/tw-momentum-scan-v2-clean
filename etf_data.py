"""ETF quantity increases, from Fugle licensed endpoint or user-supplied CSV.
Only contemporaneously dated quantityChange > 0 qualifies; missing data is unknown.
"""
from __future__ import annotations
import csv
import os
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
import requests
from data_sources import fetch_json_reliably, session

API_ROOT = 'https://api.fugle.tw/marketdata/v1.0/stock/ownership/etf-holdings'

def load_csv(path: str):
    records = defaultdict(lambda: defaultdict(list))
    available_dates=set()
    with Path(path).open(encoding='utf-8-sig',newline='') as file:
        reader=csv.DictReader(file)
        needed={'date','etf','code','quantity_change'}
        if not reader.fieldnames or not needed.issubset(reader.fieldnames):
            raise ValueError('ETF CSV requires date,etf,code,quantity_change')
        for r in reader:
            day,etf,code = r['date'].strip(),r['etf'].strip(),r['code'].strip()
            if not re.fullmatch(r'20\d{2}-\d{2}-\d{2}',day) or not re.fullmatch(r'[1-9]\d{3}',code):
                raise ValueError('Invalid ETF CSV date/code')
            available_dates.add(day)
            delta=float(r['quantity_change'])
            if delta>0:
                records[day][code].append({'etf':etf,'quantity_change':delta})
    return records,{'status':'available','source':f'ETF CSV {path}','queried':[],'failed':[],'complete_days':sorted(available_dates), 'note':'Verify that CSV snapshots were published by each signal session close.'}

def fetch_holdings(start: str, through: str, symbols: list[str] | None = None):
    key=os.getenv('FUGLE_API_KEY','').strip()
    symbols = symbols or [s.strip() for s in os.getenv('ETF_SYMBOLS','0050,00981A,00403A').split(',') if s.strip()]
    if not key:
        return {},{'status':'unavailable','source':'Fugle ETF Holdings',
                   'queried':symbols,'failed':symbols,
                   'note':'No FUGLE_API_KEY; B1 is unknown (never counted as triggered).'}
    s=session()
    s.headers['X-API-KEY']=key
    begin=date.fromisoformat(start)
    last=date.fromisoformat(through)
    records=defaultdict(lambda: defaultdict(list))
    success=[]; failed=[]; observed_days=defaultdict(set)
    for symbol in symbols:
        if not re.fullmatch(r'[0-9A-Z]{4,6}',symbol):
            failed.append(symbol);continue
        cursor=begin
        ok=True
        while cursor<=last:
            end=min(last,cursor+timedelta(days=295))
            try:
                raw=fetch_json_reliably(s,f'{API_ROOT}/{symbol}',params={'from':cursor.isoformat(),
                        'to':end.isoformat(),'sort':'asc'},timeout=60,
                        label=f'Fugle ETF holdings {symbol}')
                if not isinstance(raw,dict) or not isinstance(raw.get('data'),list):
                    raise ValueError('ETF holdings malformed response')
                for snapshot in raw['data']:
                    day=snapshot.get('date')
                    if not day or not (cursor.isoformat()<=day<=end.isoformat()):continue
                    observed_days[day].add(symbol)
                    for component in snapshot.get('components',[]):
                        code=str(component.get('symbol','')).strip()
                        delta=component.get('quantityChange')
                        if not re.fullmatch(r'[1-9][0-9]{3}',code) or delta is None:
                            continue
                        delta=float(delta)
                        if delta>0:
                            records[day][code].append({'etf':symbol,'quantity_change':delta})
            except (ValueError, RuntimeError, requests.RequestException) as exc:
                print(f'[ETF] {symbol}: {type(exc).__name__}: {str(exc)[:250]}', flush=True)
                ok=False; break
            cursor=end+timedelta(days=1)
        (success if ok else failed).append(symbol)
    status = 'available' if not failed and success else ('partial' if success else 'unavailable')
    complete_days=[day for day,covered in observed_days.items() if set(symbols).issubset(covered)]
    return records,{'status':status,'source':'Fugle ETF Holdings API',
                    'queried':symbols,'succeeded':success,'failed':failed,'complete_days':sorted(complete_days),
                    'note':('quantityChange vs previous available ETF disclosure, not necessarily previous trade session. '
                            'Disclosure timestamp is not verified; backtests are retrospective.')}
