"""Pure momentum strategy + deterministic session-by-session watchlist replay.
All volume inputs are shares; rules involving 6000 / 15000 use board lots (=1000 shares).
All prices are unadjusted exchange closes (see README for limitations).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import math
import pandas as pd

TRACKING_START = "2026-10-19"
RSI_PERIOD, KDJ_PERIOD = 14, 9
BEAR_VOLUME_RATIO = 1.0    # strictly greater than prior day
BEAR_BODY_FRACTION = .05   # (open-close)/open >= 5%


def wilder_rsi(closes: pd.Series, n: int = RSI_PERIOD) -> pd.Series:
    closes = pd.Series(closes, dtype=float).reset_index(drop=True)
    out = pd.Series(float('nan'), index=closes.index)
    if len(closes) < n + 1:
        return out
    changes = closes.diff()
    gains, losses = changes.clip(lower=0), (-changes).clip(lower=0)
    avg_up = float(gains.iloc[1:n+1].mean())
    avg_down = float(losses.iloc[1:n+1].mean())
    for i in range(n, len(closes)):
        if i > n:
            avg_up = (avg_up * (n - 1) + max(0.0, float(changes.iloc[i]))) / n
            avg_down = (avg_down * (n - 1) + max(0.0, -float(changes.iloc[i]))) / n
        out.iloc[i] = 100 * avg_up / (avg_up + avg_down) if avg_up+avg_down else 50.
    return out


def kdj(high: pd.Series, low: pd.Series, close: pd.Series, n: int = KDJ_PERIOD):
    """Taiwanese 9,3,3 recursive stochastic. K_0=D_0=50; RSV=50 when range=0."""
    hi, lo, cl = map(lambda s: pd.Series(s, dtype=float).reset_index(drop=True), (high,low,close))
    k, d = pd.Series(float('nan'), index=cl.index), pd.Series(float('nan'), index=cl.index)
    prev_k = prev_d = 50.
    for i in range(n - 1, len(cl)):
        upper = float(hi.iloc[i-n+1:i+1].max())
        lower = float(lo.iloc[i-n+1:i+1].min())
        rsv = (100 * (float(cl.iloc[i])-lower)/(upper-lower)) if upper > lower else 50.
        prev_k = (2 * prev_k + rsv) / 3
        prev_d = (2 * prev_d + prev_k) / 3
        k.iloc[i], d.iloc[i] = prev_k, prev_d
    return k, d


def percent_change(new:float, old:float):
    return (new / old - 1.) * 100. if old > 0 else float('nan')


def prepare_indicators(bars):
    """Precompute per-symbol indicators once; replay remains fast after years of sessions."""
    cl=pd.Series([float(x['close']) for x in bars],dtype=float)
    vol=pd.Series([float(x['volume']) for x in bars],dtype=float)
    hi=pd.Series([float(x['high']) for x in bars],dtype=float)
    lo=pd.Series([float(x['low']) for x in bars],dtype=float)
    rs=wilder_rsi(cl)
    k,d=kdj(hi,lo,cl)
    return {'close':cl,'volume':vol,'rsi':rs,'k':k,'d':d,
            'ma':{n:cl.rolling(n).mean() for n in (10,20,60,120)},
            'v3':vol.rolling(3).mean()/1000.,'v12':vol.rolling(12).mean()/1000.,
            'prev3':cl.shift(1).rolling(3).mean()}


def compute_metrics(bars, index, prepared=None):
    """Evaluate only bars <= index; prepared indicators use past and present data only."""
    if index < 120:return None
    p=prepared if prepared is not None else prepare_indicators(bars[:index+1])
    cl,vol=p['close'],p['volume']
    rs,k,d=p['rsi'],p['k'],p['d']
    i=index if prepared is not None else len(cl)-1
    fields=[rs.iloc[i],rs.iloc[i-1],k.iloc[i],k.iloc[i-1],d.iloc[i]]
    if any(not math.isfinite(float(x)) for x in fields):return None
    today,yesterday=bars[index],bars[index-1]
    close,prev_close=float(cl.iloc[i]),float(cl.iloc[i-1])
    vol_lots=float(vol.iloc[i])/1000.
    ma={n:float(m.iloc[i]) for n,m in p['ma'].items()}
    vol3,vol12=float(p['v3'].iloc[i]),float(p['v12'].iloc[i])
    ret1=percent_change(close,prev_close)
    ret_prev=percent_change(prev_close,float(cl.iloc[i-2]))
    ret5=percent_change(close,float(cl.iloc[i-5]))
    c3=(float(rs.iloc[i])>float(rs.iloc[i-1])>70 and
        float(k.iloc[i])>float(d.iloc[i])>50 and float(k.iloc[i])>float(k.iloc[i-1]))
    c4=(ret1>5 and ret_prev>5) or ret5>20
    mandatory=(vol3>vol12 and ma[20]>ma[60]>ma[120] and
               ((close>200 and vol_lots>6000) or (50<close<200 and vol_lots>15000)))
    e1=close<ma[10]
    e2=(float(vol.iloc[i])>float(vol.iloc[i-1])*BEAR_VOLUME_RATIO and
        (float(today['open'])-close)/float(today['open'])>=BEAR_BODY_FRACTION and
        close<float(yesterday['low']))
    return {'date':today['date'],'code':today['code'],'name':today['name'],
            'close':close,'volume_lots':vol_lots,'volume_ratio':vol3/vol12 if vol12>0 else float('nan'),
            'vol3_lots':vol3,'vol12_lots':vol12,'ma10':ma[10],'ma20':ma[20],
            'ma60':ma[60],'ma120':ma[120], 'rsi':float(rs.iloc[i]),
            'rsi_prev':float(rs.iloc[i-1]),'k':float(k.iloc[i]),'k_prev':float(k.iloc[i-1]),
            'd':float(d.iloc[i]), 'daily_change_pct':ret1,'prev_change_pct':ret_prev,
            'five_day_return_pct':ret5,'three_prev_close_avg':float(p['prev3'].iloc[i]),
            'mandatory':bool(mandatory),'B2':bool(close>float(p['prev3'].iloc[i])),
            'B3':bool(c3),'B4':bool(c4),'E1':bool(e1),'E2':bool(e2),
            'chart':[{'date':x['date'],'close':float(x['close'])} for x in bars[max(0,i-9):i+1]]}


def with_etf_flag(metrics, etf_by_date, etf_status, etf_complete_days=None):
    """B1 is None if ETF data unavailable, and only true for same-day verified increase."""
    m = dict(metrics)
    items = etf_by_date.get(m['date'], {}).get(m['code'], [])
    m['B1'] = True if items else (False if etf_status == 'available' and (etf_complete_days is None or m['date'] in etf_complete_days) else None)
    m['etf_detail'] = '; '.join(f"{x['etf']} +{x['quantity_change']:,.0f}股" for x in items)
    m['entry_conditions'] = [key for key in ('B1','B2','B3','B4') if m[key] is True]
    return m


def run_replay(bars_by_code: dict, trading_dates: list[str], as_of: str,
               etf_by_date=None, etf_status='unavailable', start=TRACKING_START, etf_complete_days=None,
               min_bars=121, require_market_data=True):
    """Fresh reconstruction every run. Entry on qualifying session close; exit on exit-signal close.
    Never qualifies a trade on a date where that stock lacks its own session bar.
    """
    etf_by_date = etf_by_date or {}
    days = [d for d in sorted(set(trading_dates)) if start <= d <= as_of]
    if not days: return {'watchlist':[],'added':[],'removed':[], 'continuous':[],
                         'ledger':[],'daily_rows':[], 'latest':None,'blocked':[], 'days':0}
    last = days[-1]
    current = {}
    ledger, daily_rows, change_rows, blocked = [], [], [], []
    prepared = {}
    for code, bars in bars_by_code.items():
        bars = sorted((x for x in bars if x['date']<=as_of),key=lambda v:v['date'])
        if not bars:continue
        # Store date -> position; simple per-stock T-series (never assume missing trade == exit)
        prepared[code] = (bars,{x['date']:i for i,x in enumerate(bars)},prepare_indicators(bars))
    added_today, removed_today = [], []
    for day in days:
        add, remove = [], []
        for code,(bars,indices,indicators) in prepared.items():
            ix=indices.get(day)
            if ix is None:
                if code in current:
                    current[code]['stale']=True
                continue
            if ix < min_bars-1:continue
            m = compute_metrics(bars, ix, indicators)
            if m is None:continue
            m = with_etf_flag(m, etf_by_date, etf_status, etf_complete_days)
            if code in current:
                ticket = current[code]
                if m['E1'] or m['E2']:
                    gone=dict(m,entry_date=ticket['entry_date'],entry_price=ticket['entry_price'],
                              entry_conditions=ticket['entry_conditions'],
                              held_sessions=ticket['held_sessions']+1,
                              cumulative_return_pct=percent_change(m['close'],ticket['entry_price']),
                              exit_conditions=[e for e in ('E1','E2') if m[e]])
                    remove.append(gone)
                    ledger.append({'code':code,'name':m['name'],'entry_date':ticket['entry_date'],
                                   'entry_close':ticket['entry_price'],'exit_date':day,
                                   'exit_close':m['close'], 'return_pct':gone['cumulative_return_pct'],
                                   'held_sessions':gone['held_sessions'],'entry_conditions':','.join(ticket['entry_conditions']),
                                   'exit_conditions':','.join(gone['exit_conditions'])})
                    del current[code]
                    change_rows.append({'date':day,'code':code,'type':'removed','reason':','.join(gone['exit_conditions'])})
                    continue
                ticket['held_sessions'] += 1
                ticket['latest']=m
                ticket['stale']=False
            elif m['mandatory'] and m['entry_conditions']:
                if m['E1'] or m['E2']:
                    blocked.append(dict(m, reason=','.join(e for e in ('E1','E2') if m[e])))
                else:
                    current[code] = {'entry_date':day,'entry_price':m['close'],
                                     'entry_conditions':list(m['entry_conditions']),
                                     'entry_etf_detail':m.get('etf_detail',''),
                                     'held_sessions':1,'latest':m,'stale':False}
                    add.append(dict(m, entry_date=day))
                    change_rows.append({'date':day,'code':code,'type':'added',
                                        'reason':','.join(m['entry_conditions'])})
        # Snapshot every day, with explicit stale quote flag for suspended/missing market data.
        for code,t in current.items():
            m=t['latest']
            daily_rows.append({'date':day,'code':code,'name':m['name'],'quote_date':m['date'],
                               'entry_date':t['entry_date'],'entry_close':t['entry_price'],
                               'close':m['close'],'return_pct':percent_change(m['close'],t['entry_price']),
                               'held_sessions':t['held_sessions'], 'stale':t['stale']})
        if day==last: added_today,removed_today=add,remove
    watch=[]
    for code,t in current.items():
        m=t['latest']
        watch.append(dict(m,entry_date=t['entry_date'],entry_price=t['entry_price'],
                          entry_conditions=t['entry_conditions'],entry_etf_detail=t.get('entry_etf_detail',''),held_sessions=t['held_sessions'],
                          cumulative_return_pct=percent_change(m['close'],t['entry_price']),
                          stale=t['stale']))
    watch.sort(key=lambda m:(-m['cumulative_return_pct'],m['code']))
    return {'watchlist':watch,'added':sorted(added_today,key=lambda m:m['code']),
            'removed':sorted(removed_today,key=lambda m:m['code']),
            'continuous':[m for m in watch if m['held_sessions']>=2],
            'ledger':ledger,'daily_rows':daily_rows,'changes':change_rows,
            'latest':last,'blocked':[b for b in blocked if b['date']==last], 'days':len(days)}
