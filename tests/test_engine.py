import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from datetime import date, timedelta
import pandas as pd
from engine import compute_metrics, kdj, wilder_rsi,with_etf_flag,run_replay


def bars(closes=None,volumes=None,start='2026-04-01'):
    closes=closes or [210+i*.5 for i in range(150)]
    volumes=volumes or [7_000_000]*len(closes)
    days=pd.bdate_range(start,periods=len(closes))
    return [{'date':d.strftime('%Y-%m-%d'),'code':'2330','name':'測試股',
             'open':float(c)-.3,'high':float(c)+2,'low':float(c)-3,
             'close':float(c),'volume':v,'market':'上市'}
             for d,c,v in zip(days,closes,volumes)]

class TestMomentum(unittest.TestCase):
    def test_rsi_rising(self):
        rs=wilder_rsi(pd.Series(list(range(100))))
        self.assertAlmostEqual(rs.iloc[-1],100)
    def test_rsi_flat(self):
        rs=wilder_rsi(pd.Series([100.]*50))
        self.assertEqual(rs.iloc[-1],50)
    def test_kdj_seed(self):
        h=pd.Series([15]*10);l=pd.Series([5]*10);cl=pd.Series([10]*10)
        k,d=kdj(h,l,cl);self.assertAlmostEqual(k.iloc[-1],50)
        self.assertAlmostEqual(d.iloc[-1],50)
    def test_entry_mandatory_and_b2(self):
        b=bars(volumes=[7_000_000]*146+[8_000_000]*4)
        m=compute_metrics(b,len(b)-1)
        self.assertTrue(m['mandatory']);self.assertTrue(m['B2']);self.assertFalse(m['E1'])
    def test_no_volume_expansion(self):
        b=bars();self.assertFalse(compute_metrics(b,len(b)-1)['mandatory'])
    def test_threshold_close_200_rejected(self):
        b=bars(closes=[200]*150,volumes=[20_000_000]*146+[21_000_000]*4)
        self.assertFalse(compute_metrics(b,len(b)-1)['mandatory'])
    def test_threshold_close_50_rejected(self):
        b=bars(closes=[50]*150,volumes=[20_000_000]*146+[21_000_000]*4)
        self.assertFalse(compute_metrics(b,len(b)-1)['mandatory'])
    def test_must_require_all_mas(self):
        b=bars(closes=[280-i*.5 for i in range(150)],volumes=[10_000_000]*146+[13_000_000]*4)
        self.assertFalse(compute_metrics(b,len(b)-1)['mandatory'])
    def test_b4_double_daily_greater_than_five(self):
        cc=[200]*147+[212,225,238]
        v=[7_000_000]*146+[9_000_000]*4
        m=compute_metrics(bars(cc,v),149)
        self.assertTrue(m['B4']);self.assertGreater(m['daily_change_pct'],5)
    def test_b4_five_day_return(self):
        cc=[200]*144+[201,205,211,219,231,243]
        m=compute_metrics(bars(cc,[8_000_000]*150),149)
        self.assertTrue(m['B4']);self.assertGreater(m['five_day_return_pct'],20)
    def test_very_big_red_k(self):
        b=bars(volumes=[7_000_000]*148+[8_000_000,9_000_000])
        b[-1]['open']=290;b[-1]['close']=270;b[-1]['low']=260
        b[-2]['low']=272
        m=compute_metrics(b,149);self.assertTrue(m['E2'])
    def test_bear_needs_breach_prior_low(self):
        b=bars(volumes=[7_000_000]*148+[8_000_000,9_000_000])
        b[-1]['open']=290;b[-1]['close']=270;b[-1]['low']=260
        b[-2]['low']=268
        m=compute_metrics(b,149);self.assertFalse(m['E2'])
    def test_bear_needs_volume(self):
        b=bars(volumes=[7_000_000]*148+[9_000_000,8_000_000])
        b[-1]['open']=290;b[-1]['close']=270;b[-1]['low']=260
        b[-2]['low']=272
        m=compute_metrics(b,149);self.assertFalse(m['E2'])
    def test_etf_unavailable_unknown(self):
        m=compute_metrics(bars(volumes=[7_000_000]*146+[8_000_000]*4),149)
        a=with_etf_flag(m,{},'unavailable')
        self.assertIsNone(a['B1']);self.assertNotIn('B1',a['entry_conditions'])
    def test_etf_increase_flag(self):
        b=bars();m=compute_metrics(b,149)
        etf={m['date']:{m['code']:[{'etf':'0050','quantity_change':350}]}}
        a=with_etf_flag(m,etf,'available')
        self.assertTrue(a['B1'])
    def test_replay_since_start_and_exit(self):
        b=bars(volumes=[7_000_000]*146+[8_000_000]*4)
        d0=b[-3]['date'];d1=b[-2]['date'];d2=b[-1]['date']
        # Enter d0, hold d1, exit d2 on E1 + bear volume candle
        b[-1]['open']=285;b[-1]['close']=265;b[-1]['high']=286;b[-1]['low']=260
        b[-2]['low']=270
        r=run_replay({'2330':b},[x['date'] for x in b],d2,start=d0)
        self.assertEqual(len(r['ledger']),1)
        self.assertEqual(r['ledger'][0]['exit_date'],d2)
        self.assertEqual(len(r['watchlist']),0)
        self.assertEqual(len(r['removed']),1)
        self.assertEqual(r['removed'][0]['entry_date'],d0)
    def test_replay_continuous(self):
        b=bars(volumes=[7_000_000]*146+[8_000_000]*4)
        d0=b[-2]['date'];d1=b[-1]['date']
        r=run_replay({'2330':b},[x['date'] for x in b],d1,start=d0)
        self.assertEqual(len(r['added']),0)
        self.assertEqual(len(r['continuous']),1)
        self.assertEqual(r['continuous'][0]['held_sessions'],2)
    def test_same_day_entry_and_exit_blocked(self):
        b=bars(volumes=[7_000_000]*146+[8_000_000]*4)
        b[-1]['open']=305;b[-1]['close']=280;b[-1]['high']=310;b[-1]['low']=275
        b[-2]['low']=285
        d=b[-1]['date']
        etf={d:{'2330':[{'etf':'0050','quantity_change':100}]}}
        r=run_replay({'2330':b},[x['date'] for x in b],d,etf,'available',start=d)
        self.assertFalse(r['watchlist']);self.assertEqual(len(r['blocked']),1)

if __name__=='__main__':unittest.main()
