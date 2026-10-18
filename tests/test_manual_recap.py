import unittest
from unittest.mock import patch
import screener


def candles(n, d='2026-10-16'):
    return [{'date': d, 'code': str(2300+i), 'name': 'TEST'} for i in range(n)]


class TestManualPriorSession(unittest.TestCase):
    def test_weekend_manual_uses_last_session_without_dated_api_calls(self):
        with patch.object(screener.ds,'historical_twse') as tw:
            out=screener.choose_latest_session(object(),candles(120),candles(120),'2026-10-16','2026-10-18',True)
            self.assertEqual(out[2:],('2026-10-16',True))
            tw.assert_not_called()

    def test_weekend_scheduled_would_skip(self):
        self.assertIsNone(screener.choose_latest_session(object(),[],[],'2026-10-16','2026-10-18',False))

    def test_weekday_holiday_manual_can_use_last_session(self):
        with patch.object(screener.ds,'historical_twse',return_value=[]) as tw:
            out=screener.choose_latest_session(object(),candles(120),candles(120),'2026-10-16','2026-10-19',True)
            self.assertEqual(out[2:],('2026-10-16',True))
            tw.assert_called_once()

    def test_weekday_normal_trading_day_uses_dated_data_even_if_openapi_lags(self):
        with patch.object(screener.ds,'historical_twse',return_value=candles(120,'2026-10-19')) as tw, \
             patch.object(screener.ds,'historical_tpex',return_value=candles(120,'2026-10-19')) as tp:
            out=screener.choose_latest_session(object(),candles(120),candles(120),'2026-10-16','2026-10-19',True)
            self.assertEqual(out[2:],('2026-10-19',False))
            tw.assert_called_once();tp.assert_called_once()

    def test_incomplete_dated_tpex_does_not_use_stale(self):
        with patch.object(screener.ds,'historical_twse',return_value=candles(120)), \
             patch.object(screener.ds,'historical_tpex',return_value=candles(99)):
            with self.assertRaisesRegex(RuntimeError,'incomplete'):
                screener.choose_latest_session(object(),candles(120),candles(120),'2026-10-16','2026-10-19',True)

    def test_current_date_not_flagged_as_recap(self):
        out=screener.choose_latest_session(object(),[],[],'2026-10-19','2026-10-19',True)
        self.assertEqual(out[2:],('2026-10-19',False))

    def test_future_date_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'later than'):
            screener.choose_latest_session(object(),[],[],'2026-10-20','2026-10-19',True)

    def test_default_etf_symbols(self):
        import inspect
        from etf_data import fetch_holdings
        self.assertIn('0050,00981A,00403A',inspect.getsource(fetch_holdings))


if __name__=='__main__':unittest.main()
