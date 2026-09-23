import datetime as dt
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import radar

FIXTURE=json.loads((Path(__file__).parent/'fixtures/us_model_parity.json').read_text())
class RadarTests(unittest.TestCase):
    def entries(self):return json.loads(json.dumps(FIXTURE['entries']))
    def test_existing_us_model_numerical_parity(self):
        rows,_=radar.metrics(self.entries());actual={r['ticker']:r for r in rows}
        for expected in FIXTURE['expected']:
            result=actual[expected['ticker']]
            for key in ('score','r20','r60','r120','rs20','rs60','rs120','ema20','sma50','sma120','atr14','atr_pct','dist_ema_atr','from_high120','breakout_trigger','pullback_low','pullback_high','stop_ref','stop_pct','vol20_ann','adtv20'):
                self.assertAlmostEqual(result[key],expected[key],places=10,msg=f'{expected["ticker"]} {key}')
            self.assertEqual(result['setup'],expected['setup'])
            self.assertEqual(result['trend_aligned'],expected['trend_aligned'])
    def test_mismatched_calendar_excluded(self):
        entries=self.entries();entries['510050']['rows'].pop(-20)
        rows,_=radar.metrics(entries)
        self.assertIsNone(next(r for r in rows if r['ticker']=='510050')['score'])
    def test_short_history_excluded(self):
        entries=self.entries();entries['510050']['rows']=entries['510050']['rows'][-120:]
        rows,_=radar.metrics(entries)
        self.assertFalse(next(r for r in rows if r['ticker']=='510050')['eligible'])
    def test_stale_series_excluded(self):
        entries=self.entries();entries['510050']['rows'].pop()
        rows,_=radar.metrics(entries)
        self.assertFalse(next(r for r in rows if r['ticker']=='510050')['eligible'])
    def test_incomplete_daily_bar_cutoff(self):
        now=dt.datetime(2026,9,23,14,tzinfo=radar.TZ)
        self.assertEqual(radar.completed_cutoff(now),dt.date(2026,9,22))
        self.assertEqual(radar.completed_cutoff(now.replace(hour=16)),dt.date(2026,9,23))
    def test_weekend_cutoff(self):
        self.assertEqual(radar.completed_cutoff(dt.datetime(2026,9,20,16,tzinfo=radar.TZ)),dt.date(2026,9,18))
    def test_normalization_rejects_invalid_ohlc_and_future(self):
        stamp=int(dt.datetime(2026,9,23,tzinfo=radar.TZ).timestamp()*1000)
        row=dict(date_ms=stamp,open_price=1,high_price=2,low_price=.5,close_price=1.5,volume=100,turnover=150)
        self.assertEqual(len(radar.normalize([row,row],dt.date(2026,9,23))),1)
        self.assertFalse(radar.normalize([row],dt.date(2026,9,22)))
        row['high_price']=.1
        self.assertFalse(radar.normalize([row],dt.date(2026,9,23)))
    def test_auth_failure_not_retried(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return b'{"code":2003,"request_id":"test"}'
        with patch.object(radar.urllib.request,'urlopen',return_value=Response()) as call:
            with self.assertRaises(radar.APIError):radar.request_history('510300','test-not-a-key')
        self.assertEqual(call.call_count,1)
    def test_429_business_error_retries(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return b'{"code":4001,"request_id":"test"}'
        with patch.object(radar.urllib.request,'urlopen',return_value=Response()) as call,patch.object(radar.time,'sleep'):
            with self.assertRaises(radar.APIError):radar.request_history('510300','test-not-a-key')
        self.assertEqual(call.call_count,4)

if __name__=='__main__':unittest.main()
