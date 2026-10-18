"""Self-contained HTML and CSV report, never relying on remote JS/CDNs."""
from __future__ import annotations
import csv
import html
import json
from pathlib import Path


def esc(x): return html.escape(str(x),quote=True)
def fnum(x, dec=2):
    try:return f'{float(x):,.{dec}f}'
    except (ValueError,TypeError):return '—'
def fpct(x):return f'{float(x):+.2f}%' if x is not None else '—'
def tick(condition):return '✓' if condition else ('?' if condition is None else '—')

def spark(data):
    prices=[float(p['close']) for p in data]
    if not prices:return ''
    minimum,maximum=min(prices),max(prices)
    spread=maximum-minimum or 1
    points=[(12+i*(200/max(len(prices)-1,1)), 48-40*(p-minimum)/spread) for i,p in enumerate(prices)]
    poly=' '.join(f'{x:.1f},{y:.1f}' for x,y in points)
    last_x,last_y=points[-1]
    values=', '.join(f"{p['date']} {fnum(p['close'])}" for p in data)
    line = '#058759' if prices[-1]>=prices[0] else '#b94442'
    return f'<svg viewBox="0 0 226 64" width="188" height="56" role="img" aria-label="最近十日收盤價折線圖: {esc(values)}"><title>{esc(values)}</title><line x1="10" y1="50" x2="218" y2="50" stroke="#ddd"/><polyline points="{poly}" fill="none" stroke="{line}" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"/><circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="3" fill="{line}"/></svg>'

def csv_file(path, rows, columns=None):
    rows=list(rows)
    columns=columns or (list(rows[0]) if rows else ['date','code'])
    with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({k:(';'.join(map(str,v)) if isinstance(v,list) else v) for k,v in row.items() if k in columns})

def render(result, info, path):
    today=result['latest'] or info['source_date']
    rows=result['watchlist'];added=result['added'];removed=result['removed'];cont=result['continuous']
    etf=info.get('etf',{})
    def table(title,entries,kind):
        if not entries:return '<p class="muted">無符合標的</p>'
        out=['<div class="overflow"><table><thead><tr>']
        if kind=='watch': cols=['代號／名稱','收盤價','成交量（張）','成交量倍率','當日漲跌幅','MA20 / 60 / 120','RSI / K / D','觸發條件','入選日期','最近十日收盤價']
        elif kind=='changes':cols=['異動','代號／名稱','收盤價','當日漲跌幅','原因','自入選報酬']
        else:cols=['排名','代號／名稱','入選日期','追蹤交易日','入選價','最新收盤價','累積漲跌幅','當日漲跌幅']
        out.extend('<th>'+esc(c)+'</th>' for c in cols);out.append('</tr></thead><tbody>')
        for idx,m in enumerate(entries,1):
            name=f"<strong>{esc(m['code'])}</strong><div class='muted'>{esc(m['name'])}</div>"
            pct_class='up' if m.get('daily_change_pct',0)>=0 else 'down'
            pct=f'<span class="{pct_class}">{fpct(m.get("daily_change_pct"))}</span>'
            if kind=='watch':
                cells=[name,fnum(m['close']),fnum(m['volume_lots'],0),fnum(m['volume_ratio']),pct,
                       '/'.join(fnum(m['ma'+str(n)],1) for n in (20,60,120)),
                       '/'.join(fnum(m[k],1) for k in ('rsi','k','d')),
                       ','.join(m['entry_conditions'])+ ('<div class="muted">ETF: '+esc(m['entry_etf_detail'])+'</div>' if m.get('entry_etf_detail') else ''),
                       esc(m['entry_date']),spark(m['chart'])]
            elif kind=='changes':
                label='新增' if m.get('type')=='added' else '剔除'
                conditions=','.join(m['entry_conditions'] if label=='新增' else m['exit_conditions'])
                cells=[label,name,fnum(m['close']),pct,esc(conditions),
                       (fpct(m['cumulative_return_pct']) if label=='剔除' else '—')]
            else:
                ret=m['cumulative_return_pct'];cl='up' if ret>=0 else 'down'
                cells=[str(idx),name,esc(m['entry_date']),str(m['held_sessions']),
                       fnum(m['entry_price']),fnum(m['close']),f'<strong class="{cl}">{fpct(ret)}</strong>',pct]
            out.extend('<td>'+c+'</td>' for c in cells);out.append('</tr>')
        out.append('</tbody></table></div>')
        return ''.join(out)
    changes=[dict(m,type='added') for m in added]+[dict(m,type='removed') for m in removed]
    warnings=[]
    if etf.get('status') != 'available':warnings.append('ETF 持股資料未完全取得：B1 缺資料的部分標示未知，不推定為零。')
    warnings.append('價格與累積報酬以未還原收盤價計算；不含交易成本與股利，訊號收盤後才知道，當日收盤成交屬理論假設。')
    warn_html=''.join('<p class="alert">'+esc(w)+'</p>' for w in warnings)
    content=f'''<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/><title>台股動能篩選｜{today}</title>
<style>
:root{{--bg:#f4f6f8;--card:#fff;--ink:#222c39;--light:#657284;--border:#e1e5e9}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,'Noto Sans TC',sans-serif}}
main{{max-width:1320px;margin:0 auto;padding:24px 20px 70px}} h1{{font-size:26px;margin-bottom:8px}}h2{{font-size:21px;margin:0 0 14px}}p{{margin:6px 0}}section{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px;margin:18px 0;box-shadow:0 2px 10px #1b2b4010}}
.meta{{color:var(--light);font-size:13px;margin:4px 0 14px}}.muted{{font-size:12px;color:var(--light)}}.overflow{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{padding:10px 8px;text-align:left;white-space:nowrap;border-bottom:1px solid var(--border);vertical-align:middle}}th{{background:#f5f7f9;font-weight:650}} tr:hover td{{background:#f9fbfc}}.up{{color:#b34040}}.down{{color:#087b55}}
.cards{{display:flex;gap:10px;flex-wrap:wrap}}.cards span{{border:1px solid var(--border);border-radius:8px;background:white;padding:6px 12px}}.alert{{border-left:3px solid #d5a72e;padding:7px 10px;background:#fff9e7;font-size:13px}}svg{{display:block}}
</style></head><body><main><h1>台股動能篩選系統</h1><p class="meta">資料截止日：{esc(today)}｜上市＋上櫃普通股｜追蹤起點：{esc(info['start'])}｜資料來源：{esc(info['sources'])}</p>
<div class="cards"><span>觀察：<b>{len(rows)}</b></span><span>今日新增：<b>{len(added)}</b></span><span>今日剔除：<b>{len(removed)}</b></span><span>連續兩日以上：<b>{len(cont)}</b></span></div>
{warn_html}
<section><h2>一、觀察清單</h2>{table('觀察',rows,'watch')}</section>
<section><h2>二、新增、剔除清單</h2>{table('異動',changes,'changes')}</section>
<section><h2>三、連續收益</h2><p class="meta">僅顯示已留在觀察清單至少 2 個交易日的標的；累積漲跌幅由高至低。</p>{table('收益',cont,'continuous')}</section>
<p class="meta">B1 ETF 持股：{esc(etf.get('status','unknown'))}｜已讀取 ETF：{esc(', '.join(etf.get('succeeded',[])))}｜未取得：{esc(', '.join(etf.get('failed',[])))}｜追蹤交易日數：{result['days']}。</p></main></body></html>'''
    Path(path).write_text(content,encoding='utf-8')


def write_all(folder, result, info):
    root=Path(folder);root.mkdir(parents=True,exist_ok=True)
    render(result,info,root/'report.html')
    csv_file(root/'watchlist.csv',result['watchlist'], ['date','code','name','close','volume_lots','volume_ratio','daily_change_pct','rsi','k','d','ma10','ma20','ma60','ma120','entry_conditions','entry_date','entry_price','held_sessions','cumulative_return_pct','B1','B2','B3','B4','E1','E2','stale'])
    csv_file(root/'added.csv',result['added'],['date','code','name','close','daily_change_pct','entry_conditions','B1','B2','B3','B4'])
    csv_file(root/'removed.csv',result['removed'],['date','code','name','close','daily_change_pct','entry_date','entry_price','exit_conditions','cumulative_return_pct'])
    csv_file(root/'continuous_returns.csv',result['continuous'],['date','code','name','entry_date','entry_price','close','held_sessions','cumulative_return_pct','daily_change_pct'])
    csv_file(root/'trades.csv',result['ledger'],['code','name','entry_date','entry_close','exit_date','exit_close','return_pct','held_sessions','entry_conditions','exit_conditions'])
    csv_file(root/'daily_watchlist.csv',result['daily_rows'])
    csv_file(root/'changes.csv',result['changes'])
    csv_file(root/'blocked_entries.csv',result['blocked'],['date','code','name','close','reason','entry_conditions'])
    with (root/'metadata.json').open('w',encoding='utf-8') as f:
        json.dump({**info,'counts':{k:len(result[k]) for k in ('watchlist','added','removed','continuous','ledger','daily_rows','blocked')},'as_of':result['latest']},f,ensure_ascii=False,indent=2)
    with (root/'report.md').open('w',encoding='utf-8') as f:
        f.write(f"# 台股動能 {result['latest']}\n\n一、觀察清單：{len(result['watchlist'])} 檔；二、新增 {len(result['added'])}、剔除 {len(result['removed'])}；三、連續收益 {len(result['continuous'])} 檔。\n\n詳見 report.html 與各 CSV。\n")
