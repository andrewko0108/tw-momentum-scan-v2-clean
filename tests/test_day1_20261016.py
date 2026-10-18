"""October 16, 2026 is Day 1 for the V2 momentum strategy."""
import unittest
from unittest.mock import patch

import pandas as pd

import screener
from engine import TRACKING_START, run_replay
from data_sources import TRACKING_START as HISTORY_TRACKING_START
from test_engine import bars


def dummy_quotes(n, day='2026-10-16'):
    return [{'date':day, 'code':str(2000+i), 'name':'test'} for i in range(n)]


class TestDayOne20261016(unittest.TestCase):
    def test_engine_and_history_start_on_oct_16(self):
        self.assertEqual(TRACKING_START, '2026-10-16')
        self.assertEqual(HISTORY_TRACKING_START, TRACKING_START)

    def test_day1_can_add_but_not_yet_continuous(self):
        start=(pd.Timestamp('2026-10-16')-pd.offsets.BDay(149)).strftime('%Y-%m-%d')
        items=bars(volumes=[7_000_000]*146+[8_000_000]*4, start=start)
        self.assertEqual(items[-1]['date'],'2026-10-16')
        result=run_replay({'2330':items},[r['date'] for r in items],'2026-10-16')
        self.assertEqual(result['latest'],'2026-10-16')
        self.assertEqual(result['days'],1)
        self.assertEqual(len(result['added']),1)
        self.assertEqual(len(result['watchlist']),1)
        self.assertEqual(result['continuous'],[])
        self.assertEqual(result['watchlist'][0]['entry_date'],'2026-10-16')

    def test_manual_historical_uses_exact_date_not_latest_market_api(self):
        with patch.object(screener.ds,'historical_twse',return_value=dummy_quotes(650)) as tw, \
             patch.object(screener.ds,'historical_tpex',return_value=dummy_quotes(450)) as tp, \
             patch.object(screener.ds,'fetch_official_latest_pair') as latest:
            result=screener.choose_exact_session(object(),'2026-10-16','2026-10-19')
        self.assertEqual(result[2],'2026-10-16')
        tw.assert_called_once()
        self.assertEqual(tw.call_args.args[1],'2026-10-16')
        tp.assert_called_once()
        latest.assert_not_called()

    def test_reject_future_requested_date(self):
        with patch.object(screener.ds,'historical_twse') as tw:
            with self.assertRaisesRegex(ValueError,'future session'):
                screener.choose_exact_session(object(),'2026-10-20','2026-10-19')
            tw.assert_not_called()

    def test_reject_incomplete_exact_date(self):
        with patch.object(screener.ds,'historical_twse',return_value=dummy_quotes(650)), \
             patch.object(screener.ds,'historical_tpex',return_value=dummy_quotes(200)):
            with self.assertRaisesRegex(RuntimeError,'incomplete'):
                screener.choose_exact_session(object(),'2026-10-16','2026-10-19')


if __name__=='__main__':
    unittest.main()
