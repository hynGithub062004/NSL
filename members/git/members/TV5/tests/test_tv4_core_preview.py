"""Offline unit tests for TV5 preview-only TV4 connector; no live GNS3 required."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'members' / 'TV5'))
from tv4_core_preview import TV4PreviewClient, _policy_state


class FakeResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode('utf-8')
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return self.body


class TestTV4PreviewClient(unittest.TestCase):
    def setUp(self):
        self.client = TV4PreviewClient('http://127.0.0.1:18018')

    def test_preview_has_only_three_keys_and_no_confirm(self):
        captured = {}
        def fake_urlopen(req: Request, timeout):
            captured['url'] = req.full_url
            captured['method'] = req.get_method()
            captured['payload'] = json.loads(req.data.decode('utf-8'))
            return FakeResponse({'mode':'preview', 'status':'ok'})
        with patch('tv4_core_preview.urlopen', side_effect=fake_urlopen):
            result = self.client.preview('embb', 'low_latency', 'tv5-test-100')
        self.assertEqual(result['mode'], 'preview')
        self.assertEqual(captured['method'], 'POST')
        self.assertEqual(captured['url'], 'http://127.0.0.1:18018/apply-policy')
        self.assertEqual(captured['payload'], {
            'request_id': 'tv5-test-100', 'slice_id': 'embb', 'policy': 'low_latency',
        })
        self.assertNotIn('confirm', captured['payload'])

    def test_confirm_never_allowed(self):
        with self.assertRaises(ValueError):
            self.client._request('POST', '/apply-policy', {
                'request_id':'x','slice_id':'embb','policy':'high_bandwidth','confirm':'APPLY_TV4',
            })

    def test_core_kpi_is_slice_scoped(self):
        captured=[]
        def fake_urlopen(req, timeout):
            captured.append(req.full_url)
            return FakeResponse({'measurement':{'is_live':False},'core_kpi':{'switching_time_ms':None}})
        with patch('tv4_core_preview.urlopen', side_effect=fake_urlopen):
            self.client.core_kpi('urllc')
        self.assertEqual(captured,['http://127.0.0.1:18018/core-kpi?slice_id=urllc'])

    def test_policy_comparison_excludes_timestamps(self):
        x={'slices':{'embb':{'active_policy':'high_bandwidth','routing_table':100,'route_raw':'route-x'},
                     'urllc':{'active_policy':'low_latency','routing_table':101,'route_raw':'route-y'}},
           'checked_at_utc':'2026-11-09T00:00:00Z'}
        y=dict(x,checked_at_utc='2026-11-10T00:00:00Z')
        self.assertEqual(_policy_state(x),_policy_state(y))
        y['slices']={**x['slices'],'embb':{**x['slices']['embb'],'route_raw':'changed'}}
        self.assertNotEqual(_policy_state(x),_policy_state(y))

if __name__=='__main__':
    unittest.main()
