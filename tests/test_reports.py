import unittest
import tempfile
import sys
import os
import json
import csv
import subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine import compute_metrics,run_replay
from reports import spark,write_all
from etf_data import load_csv
from test_engine import bars

class TestReports(unittest.TestCase):
    def test_chart_svg(self):
        sample=bars()[-10:]
        result=spark(sample)
        self.assertIn('<svg',result)
        self.assertIn('polyline',result)
    def test_etf_csv(self):
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/'hold.csv'
            file.write_text('date,etf,code,quantity_change\n2026-10-19,0050,2330,500\n2026-10-20,0050,2330,-200\n',encoding='utf-8')
            out,metadata=load_csv(str(file))
            self.assertEqual(metadata['status'],'available')
            self.assertEqual(len(out['2026-10-19']['2330']),1)
            self.assertNotIn('2330',out['2026-10-20'])
    def test_coverage_incomplete_has_unknown_not_false(self):
        m=compute_metrics(bars(),149)
        from engine import with_etf_flag
        a=with_etf_flag(m,{},'available',etf_complete_days=set())
        self.assertIsNone(a['B1'])
    def test_generated_dashboard_and_csv(self):
        b=bars(volumes=[7_000_000]*146+[8_000_000]*4)
        date1=b[-2]['date'];date2=b[-1]['date']
        result=run_replay({'2330':b},[x['date'] for x in b],date2,start=date1)
        info={'source_date':date2,'start':date1,'sources':'simulated','etf':{'status':'unavailable','queried':[],'failed':[]}}
        with tempfile.TemporaryDirectory() as folder:
            write_all(folder,result,info)
            p=Path(folder)
            self.assertTrue((p/'report.html').is_file())
            self.assertTrue((p/'continuous_returns.csv').is_file())
            self.assertTrue((p/'trades.csv').is_file())
            report=(p/'report.html').read_text()
            for label in ('一、觀察清單','二、新增、剔除清單','三、連續收益'):
                self.assertIn(label,report)
            self.assertIn('polyline',report)
            self.assertEqual(json.loads((p/'metadata.json').read_text())['counts']['continuous'],1)
    def test_offline_cli_end_to_end(self):
        b=bars(volumes=[7_000_000]*146+[8_000_000]*4)
        as_of=b[-1]['date'];first=b[-2]['date']
        base=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);csv_file=root/'history.csv';sector=root/'sectors.csv';result=root/'out'
            with csv_file.open('w',encoding='utf-8',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=['date','code','name','volume','open','high','low','close'])
                writer.writeheader();writer.writerows({k:v for k,v in row.items() if k not in ('market',)} for row in b)
            sector.write_text('market,code,industry\n上市,2330,24\n',encoding='utf-8')
            r=subprocess.run([sys.executable,'screener.py','--csv',str(csv_file),'--sectors',str(sector),
                              '--as-of',as_of,'--start',first,'--output',str(result)],
                              cwd=base, capture_output=True,text=True,timeout=35)
            self.assertEqual(r.returncode,0,r.stdout+'\n'+r.stderr)
            self.assertTrue((result/'report.html').exists())
            self.assertIn('2330',(result/'watchlist.csv').read_text(encoding='utf-8-sig'))

if __name__=='__main__':unittest.main()
