"""Prevent future deployments from recreating the Groww/FYERS aiohttp conflict."""
import io
import json
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from app.brokers.streams import _fyers_worker_python
from app.brokers import fyers_feed_worker
from app.brokers.base import BrokerError

BACKEND = Path(__file__).resolve().parents[1]


class BrokerSdkIsolationTests(unittest.TestCase):
    def test_main_requirements_do_not_mix_incompatible_sdks(self):
        requirements = (BACKEND / 'requirements.txt').read_text()
        self.assertIn('growwapi>=1.5.0', requirements)
        self.assertNotIn('\nfyers-apiv3', requirements)
        self.assertIn('fyers-apiv3', (BACKEND / 'requirements-fyers-worker.txt').read_text())
        dockerfile = (BACKEND / 'Dockerfile').read_text()
        self.assertIn('/opt/tradeverse-main', dockerfile)
        self.assertIn('/opt/tradeverse-fyers', dockerfile)
        self.assertIn('pip check', dockerfile)

    def test_missing_fyers_venv_fails_closed(self):
        with patch.dict(os.environ, {'FYERS_WORKER_PYTHON': '/path/that/does/not/exist'}):
            with self.assertRaisesRegex(BrokerError, 'isolated SDK interpreter'):
                _fyers_worker_python()

    def test_isolated_fyers_worker_emits_ticks_not_tokens(self):
        token = 'very_secret_test_token_not_for_logs'
        frames = []
        data_ws = types.ModuleType('fyers_apiv3.FyersWebsocket.data_ws')

        class FakeFyersDataSocket:
            def __init__(self, **kwargs):
                self.on_connect = kwargs['on_connect']
                self.on_message = kwargs['on_message']
                self.on_close = kwargs['on_close']
                self.auth = kwargs['access_token']

            def subscribe(self, **kwargs):
                self.symbols = kwargs['symbols']

            def keep_running(self):
                pass

            def connect(self):
                self.on_connect()
                self.on_message({'symbol': 'NSE:RELIANCE-EQ', 'ltp': 123.5,
                                 'access_token': token})
                self.on_close()

            def close_connection(self):
                pass

        data_ws.FyersDataSocket = FakeFyersDataSocket
        pkg = types.ModuleType('fyers_apiv3')
        ws = types.ModuleType('fyers_apiv3.FyersWebsocket')
        ws.data_ws = data_ws
        stdin = io.StringIO(json.dumps({'access_token': token,
                                         'symbols': ['NSE:RELIANCE-EQ']}) + '\n')
        stdout = io.StringIO()
        with patch.dict(sys.modules, {'fyers_apiv3': pkg,
                                      'fyers_apiv3.FyersWebsocket': ws,
                                      'fyers_apiv3.FyersWebsocket.data_ws': data_ws}), \
             patch('sys.stdin', stdin), patch('sys.stdout', stdout):
            self.assertEqual(fyers_feed_worker.main(), 0)
        result = stdout.getvalue()
        self.assertNotIn(token, result)
        messages = [json.loads(line) for line in result.splitlines()]
        self.assertEqual(messages[0]['type'], 'ready')
        self.assertEqual(messages[1]['type'], 'tick')
        self.assertEqual(messages[1]['data']['ltp'], 123.5)
        self.assertNotIn('access_token', messages[1]['data'])


if __name__ == '__main__':
    unittest.main()
