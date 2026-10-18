"""Tests for the self-contained Action Summary and published one-file HTML."""
import tempfile
import unittest
from pathlib import Path

from dashboard import _spark, build_summary, write_dashboard
from engine import run_replay
from reports import write_all
from test_engine import bars


class TestDashboard(unittest.TestCase):
    def setUp(self):
        self.bars = bars(volumes=[7_000_000]*146+[8_000_000]*4)
        self.start = self.bars[-2]['date']
        self.end = self.bars[-1]['date']
        self.result = run_replay(
            {'2330':self.bars},[x['date'] for x in self.bars],self.end,start=self.start)
        self.info = {
            'source_date':self.end,'start':self.start,'execution':self.end,
            'sources':'offline fixture only','coverage':'offline sample; NOT full market',
            'universe_count':1,'report_mode':'manual_exact_session',
            'etf':{'status':'unavailable','queried':['0050','00981A','00403A']}
        }

    def test_sparkline(self):
        self.assertEqual(_spark([{'close':100}]*10),'▄'*10)
        self.assertEqual(len(_spark(self.bars[-10:])),10)

    def test_summary_contains_full_three_sections(self):
        doc=build_summary(self.result,self.info)
        for tag in ('一、觀察清單','二、新增、剔除清單','三、連續收益',
                    '代號','RSI／K／D','十日走勢','2026','2330','追蹤起點'):
            self.assertIn(tag,doc)
        self.assertIn('ETF B1',doc)
        self.assertIn('未還原',doc)

    def test_empty_results_have_readable_tables(self):
        empty={key:[] for key in ('watchlist','added','removed','continuous','ledger','blocked')}
        empty['latest']='2026-10-16'
        doc=build_summary(empty,self.info)
        self.assertIn('觀察 0 檔',doc)
        self.assertIn('無符合標的',doc)

    def test_standalone_html_contains_all_tracking_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_all(tmp,self.result,self.info)
            write_dashboard(tmp,self.result,self.info)
            html=(Path(tmp)/'report.html').read_text(encoding='utf-8')
            md=(Path(tmp)/'report.md').read_text(encoding='utf-8')
            self.assertIn('最近十日收盤價折線圖',html)
            self.assertIn('完整逐日追蹤紀錄',html)
            self.assertIn('已結束交易紀錄',html)
            self.assertIn('新增、剔除事件',html)
            self.assertIn('一、觀察清單',md)
            self.assertIn('三、連續收益',md)
            self.assertIn('2330',md)
            self.assertNotIn('https://cdn.',html)


if __name__=='__main__':
    unittest.main()
