import unittest
from datetime import datetime, time, timedelta, date
from zoneinfo import ZoneInfo

import pandas as pd

from app.brokers import mock  # noqa: F401  (registers adapter)
from app.brokers.base import (Capability, InstrumentKey, OrderRequest, Tick, UnsupportedCapability,
                              capability_matrix, get_adapter_class, Candle)
from app.brokers.mock import MockBroker
from app.live_data.candles import (CandleBuilder, bucket_start, find_gaps, heikin_ashi,
                                   resample_candles, stitch)
from app.order_execution.executor import OrderExecutor
from app.paper_trading.account import PaperAccount
from app.backtesting.engine import ChargeModel
from app.risk_management.engine import OrderIntent, RiskEngine, RiskLimits

IST = ZoneInfo("Asia/Kolkata")
KEY = InstrumentKey("NSE", "RELIANCE")


def at(h, m, s=0, d=2):
    return datetime(2025, 1, d, h, m, s, tzinfo=IST)


def intent(**kw):
    base = dict(broker_id="mock", account_id="A1", strategy_id="S1", symbol="RELIANCE", side="BUY",
                qty=10, price=100.0, mode="paper", is_exit=False)
    base.update(kw)
    return OrderIntent(**base)


class TestRisk(unittest.TestCase):
    def eng(self, **lim):
        return RiskEngine(RiskLimits(**lim))

    def test_live_disabled_by_default(self):
        r = RiskEngine()
        d = r.check(intent(mode="live"), at(10, 0), feed_age_sec=1)
        self.assertFalse(d.allowed)
        self.assertTrue(any("live trading is disabled" in x for x in d.reasons))
        r.limits.live_trading_enabled = True
        self.assertTrue(r.check(intent(mode="live"), at(10, 0), feed_age_sec=1).allowed)

    def test_wrong_account_blocked_even_for_exit(self):
        r = RiskEngine()
        r.bind_strategy("S1", "mock", "A1")
        self.assertFalse(r.check(intent(account_id="A2", is_exit=True), at(10, 0)).allowed)
        self.assertTrue(r.check(intent(), at(10, 0)).allowed)

    def test_kill_switch_blocks_entries_not_exits(self):
        r = RiskEngine()
        r.set_position("A1", "RELIANCE", 10, 100)
        r.kill_all()
        self.assertFalse(r.check(intent(), at(10, 0)).allowed)
        self.assertTrue(r.check(intent(side="SELL", is_exit=True), at(10, 0)).allowed)
        r.release_all()
        r.kill_strategy("S1")
        self.assertFalse(r.check(intent(), at(10, 0)).allowed)
        self.assertTrue(r.check(intent(strategy_id="S2"), at(10, 0)).allowed)

    def test_stale_and_unknown_feed_for_live(self):
        r = self.eng(live_trading_enabled=True)
        self.assertFalse(r.check(intent(mode="live"), at(10, 0), feed_age_sec=30).allowed)
        self.assertFalse(r.check(intent(mode="live"), at(10, 0), feed_age_sec=None).allowed)
        r.set_position("A1", "RELIANCE", 10, 100)
        self.assertTrue(r.check(intent(mode="live", side="SELL", is_exit=True), at(10, 0), feed_age_sec=30).allowed)

    def test_trading_window(self):
        r = RiskEngine()
        self.assertFalse(r.check(intent(), at(8, 0)).allowed)
        self.assertFalse(r.check(intent(), at(15, 29)).allowed)
        self.assertTrue(r.check(intent(), at(9, 30)).allowed)

    def test_size_limits(self):
        r = self.eng(max_order_qty=5, max_order_notional=500)
        d = r.check(intent(qty=10, price=100), at(10, 0))
        self.assertEqual(len(d.reasons), 2)

    def test_daily_loss_and_trades(self):
        r = self.eng(max_daily_loss=1000, max_daily_trades=2, duplicate_window_sec=0)
        r.record_pnl("A1", date(2025, 1, 2), -1000)
        r.set_position("A1", "RELIANCE", 10, 100)
        self.assertFalse(r.check(intent(), at(10, 0)).allowed)
        self.assertTrue(r.check(intent(side="SELL", is_exit=True), at(10, 0)).allowed)
        self.assertTrue(r.check(intent(), at(10, 0, d=3)).allowed)       # next day resets
        r2 = self.eng(max_daily_trades=2, duplicate_window_sec=0)
        for i in range(2):
            r2.record_submitted(intent(), at(10, i))
        self.assertFalse(r2.check(intent(), at(10, 5)).allowed)

    def test_open_positions_and_allocation(self):
        r = self.eng(max_open_positions=1, max_capital_allocation=2000)
        r.set_position("A1", "TCS", 10, 100)
        self.assertFalse(r.check(intent(symbol="INFY"), at(10, 0)).allowed)
        self.assertTrue(r.check(intent(symbol="TCS", qty=5), at(10, 0)).allowed)
        self.assertFalse(r.check(intent(symbol="TCS", qty=11), at(10, 0)).allowed)  # 1000+1100 > 2000

    def test_duplicate_and_rate_limit(self):
        r = self.eng(max_orders_per_second=3)
        r.record_submitted(intent(), at(10, 0, 0))
        self.assertFalse(r.check(intent(), at(10, 0, 2)).allowed)               # duplicate within 5s
        self.assertTrue(r.check(intent(), at(10, 0, 9)).allowed)                # window passed
        r2 = self.eng(max_orders_per_second=3, duplicate_window_sec=0)
        for i in range(3):
            r2.record_submitted(intent(symbol=f"S{i}"), at(10, 0, 0))
        self.assertFalse(r2.check(intent(symbol="Z"), at(10, 0, 0)).allowed)
        self.assertTrue(r2.check(intent(symbol="Z"), at(10, 0, 5)).allowed)

    def test_reconciliation_blocks_everything(self):
        r = RiskEngine()
        r.require_reconciliation("A1", "uncertain")
        self.assertFalse(r.check(intent(), at(10, 0)).allowed)
        self.assertFalse(r.check(intent(is_exit=True), at(10, 0)).allowed)
        self.assertTrue(r.check(intent(account_id="A2"), at(10, 0)).allowed)   # other accounts unaffected
        r.clear_reconciliation("A1")
        self.assertTrue(r.check(intent(), at(10, 0)).allowed)


class TestExecutor(unittest.IsolatedAsyncioTestCase):
    async def asetup(self, **limits):
        b = MockBroker("A1")
        await b.authenticate({})
        risk = RiskEngine(RiskLimits(live_trading_enabled=True, **limits))
        return b, risk, OrderExecutor(risk)

    def req(self, **kw):
        return OrderRequest(KEY, "BUY", 10, price=100.0, **kw)

    async def test_happy_path_attaches_client_id(self):
        b, risk, ex = await self.asetup()
        res = await ex.submit(b, self.req(), "S1", at(10, 0), feed_age_sec=1)
        self.assertEqual(res.status, "PLACED")
        self.assertTrue(res.client_order_id)
        self.assertEqual(b.orders[res.order_id].tag, res.client_order_id)

    async def test_risk_block_never_reaches_broker(self):
        b, risk, ex = await self.asetup()
        risk.kill_all()
        res = await ex.submit(b, self.req(), "S1", at(10, 0), feed_age_sec=1)
        self.assertEqual(res.status, "BLOCKED_BY_RISK")
        self.assertEqual(b.place_calls, 0)

    async def test_broker_reject(self):
        b, risk, ex = await self.asetup()
        b.failure = "reject"
        res = await ex.submit(b, self.req(), "S1", at(10, 0), feed_age_sec=1)
        self.assertEqual(res.status, "REJECTED")
        self.assertIsNone(risk.needs_reconciliation("A1"))

    async def test_timeout_after_accept_reconciles_and_never_resends(self):
        b, risk, ex = await self.asetup()
        b.failure = "timeout_after_accept"
        res = await ex.submit(b, self.req(), "S1", at(10, 0), feed_age_sec=1)
        self.assertEqual(res.status, "RECONCILED_FOUND")
        self.assertEqual(b.place_calls, 1)                     # exactly one attempt
        self.assertEqual(len(b.orders), 1)
        self.assertIsNone(risk.needs_reconciliation("A1"))

    async def test_timeout_lost_blocks_account_until_confirmed(self):
        b, risk, ex = await self.asetup()
        b.failure = "timeout_lost"
        res = await ex.submit(b, self.req(), "S1", at(10, 0), feed_age_sec=1)
        self.assertEqual(res.status, "UNRESOLVED")
        self.assertEqual(b.place_calls, 1)
        b.failure = None
        blocked = await ex.submit(b, self.req(), "S1", at(10, 1), feed_age_sec=1)
        self.assertEqual(blocked.status, "BLOCKED_BY_RISK")
        self.assertEqual(b.place_calls, 1)                     # still no resend
        ex.confirm_not_placed(b, res.client_order_id)
        ok = await ex.submit(b, self.req(), "S1", at(10, 2), feed_age_sec=1)
        self.assertEqual(ok.status, "PLACED")

    async def test_auth_error_blocks_account(self):
        b, risk, ex = await self.asetup()
        b.failure = "auth"
        res = await ex.submit(b, self.req(), "S1", at(10, 0), feed_age_sec=1)
        self.assertEqual(res.status, "AUTH_ERROR")
        self.assertIsNotNone(risk.needs_reconciliation("A1"))

    async def test_strategy_cannot_route_to_other_account(self):
        b, risk, ex = await self.asetup()
        risk.bind_strategy("S1", "mock", "OTHER")
        res = await ex.submit(b, self.req(), "S1", at(10, 0), feed_age_sec=1)
        self.assertEqual(res.status, "BLOCKED_BY_RISK")
        self.assertEqual(b.place_calls, 0)


class TestBrokerFramework(unittest.IsolatedAsyncioTestCase):
    async def test_unsupported_capabilities_raise_not_simulate(self):
        b = MockBroker("A1")
        with self.assertRaises(UnsupportedCapability):
            await b.get_historical_data(KEY, "5m", at(9, 15), at(15, 30))
        with self.assertRaises(UnsupportedCapability):
            await b.get_option_chain("NIFTY", None)

    def test_capability_matrix(self):
        m = capability_matrix()
        self.assertIn("mock", m)
        self.assertTrue(m["mock"][Capability.PLACE_ORDER.value])
        self.assertFalse(m["mock"][Capability.OPTION_CHAIN.value])
        self.assertEqual(m["mock"]["verification"], "test-double")
        self.assertIs(get_adapter_class("mock"), MockBroker)


class TestPaper(unittest.TestCase):
    def acct(self, **kw):
        return PaperAccount(100000, charges=ChargeModel.zero(), **kw)

    def test_market_fill_and_pnl(self):
        a = self.acct()
        a.on_tick("X", 100, bid=99.9, ask=100.1)
        a.place_order("X", "BUY", 10)
        self.assertEqual(a.orders["P1"].fill_price, 100.1)        # buys at ask
        a.on_tick("X", 110, bid=109.9, ask=110.1)
        self.assertAlmostEqual(a.unrealized(), 10 * (110 - 100.1))
        a.place_order("X", "SELL", 10)
        self.assertAlmostEqual(a.realized, 10 * (109.9 - 100.1))
        self.assertEqual(a.qty("X"), 0)
        self.assertAlmostEqual(a.cash, 100000 + a.realized)

    def test_limit_waits_until_price_trades_through(self):
        a = self.acct()
        a.on_tick("X", 100)
        o = a.place_order("X", "BUY", 5, "LIMIT", price=95)
        self.assertEqual(o.status, "OPEN")
        a.on_tick("X", 96)
        self.assertEqual(o.status, "OPEN")
        a.on_tick("X", 95)
        self.assertEqual((o.status, o.fill_price), ("COMPLETE", 95))

    def test_sl_m_triggers_then_fills(self):
        a = self.acct()
        a.on_tick("X", 100)
        a.place_order("X", "BUY", 10)
        sl = a.place_order("X", "SELL", 10, "SL_M", trigger=98)
        a.on_tick("X", 99)
        self.assertEqual(sl.status, "OPEN")
        a.on_tick("X", 97.5)
        self.assertEqual((sl.status, sl.fill_price), ("COMPLETE", 97.5))
        self.assertEqual(a.qty("X"), 0)

    def test_cancel_modify_and_idempotency(self):
        a = self.acct()
        a.on_tick("X", 100)
        o = a.place_order("X", "BUY", 5, "LIMIT", price=90, client_order_id="c1")
        again = a.place_order("X", "BUY", 5, "LIMIT", price=90, client_order_id="c1")
        self.assertIs(o, again)
        self.assertEqual(len(a.orders), 1)
        a.modify_order(o.order_id, price=101)
        a.on_tick("X", 100)
        self.assertEqual(o.status, "COMPLETE")
        self.assertFalse(a.cancel_order(o.order_id))

    def test_validation_rejects(self):
        a = self.acct(allow_short=False)
        self.assertEqual(a.place_order("X", "BUY", 0).status, "REJECTED")
        self.assertEqual(a.place_order("X", "BUY", 1, "LIMIT").status, "REJECTED")
        self.assertEqual(a.place_order("X", "SELL", 1).status, "REJECTED")
        self.assertEqual(a.place_order("X", "BUY", 1, "ICEBERG").status, "REJECTED")

    def test_flip_position_average(self):
        a = self.acct()
        a.on_tick("X", 100)
        a.place_order("X", "BUY", 10)
        a.on_tick("X", 110)
        a.place_order("X", "SELL", 25)
        self.assertEqual(a.positions["X"], [-15, 110])
        self.assertAlmostEqual(a.realized, 100)

    def test_charges_applied(self):
        a = PaperAccount(100000)
        a.on_tick("X", 100)
        a.place_order("X", "BUY", 100)
        self.assertLess(a.cash, 100000)


class TestCandles(unittest.TestCase):
    def tick(self, h, m, s, px, vol=None):
        return Tick(KEY, at(h, m, s), px, volume=vol)

    def test_bucket_alignment(self):
        self.assertEqual(bucket_start(at(9, 22), 15), at(9, 15))
        self.assertEqual(bucket_start(at(9, 30), 15), at(9, 30))
        self.assertEqual(bucket_start(at(9, 14), 15), at(9, 15))
        self.assertEqual(bucket_start(at(10, 0), 45), at(10, 0))   # 9:15 + 45m
        self.assertEqual(bucket_start(at(9, 59), 45), at(9, 15))
        self.assertEqual(bucket_start(at(10, 5), 45), at(10, 0))

    def test_ohlcv_and_close_on_new_bucket(self):
        b = CandleBuilder("5m")
        self.assertEqual(b.on_tick(self.tick(9, 15, 1, 100, 1000)), [])
        b.on_tick(self.tick(9, 16, 0, 103, 1100))
        b.on_tick(self.tick(9, 17, 0, 99, 1150))
        closed = b.on_tick(self.tick(9, 20, 0, 101, 1200))
        self.assertEqual(len(closed), 1)
        c = closed[0]
        self.assertEqual((c.ts, c.open, c.high, c.low, c.close), (at(9, 15), 100, 103, 99, 99))
        self.assertEqual(c.volume, 150)                         # deltas after first tick
        self.assertEqual(b.current.ts, at(9, 20))

    def test_out_of_order_and_duplicates_dropped(self):
        b = CandleBuilder("5m")
        b.on_tick(self.tick(9, 15, 5, 100, 10))
        b.on_tick(self.tick(9, 15, 9, 101, 12))
        b.on_tick(self.tick(9, 15, 6, 150, 13))                # late
        b.on_tick(self.tick(9, 15, 9, 101, 12))                # exact duplicate
        self.assertEqual(b.dropped_out_of_order, 1)
        self.assertEqual(b.dropped_duplicates, 1)
        self.assertEqual(b.current.high, 101)

    def test_no_fabricated_candles_over_gap(self):
        b = CandleBuilder("5m")
        b.on_tick(self.tick(9, 15, 0, 100))
        closed = b.on_tick(self.tick(9, 40, 0, 101))           # 5 empty buckets in between
        self.assertEqual(len(closed), 1)

    def test_volume_counter_reset(self):
        b = CandleBuilder("1m")
        b.on_tick(self.tick(9, 15, 0, 100, 5000))
        b.on_tick(self.tick(9, 15, 30, 100, 80))               # counter reset
        self.assertEqual(b.current.volume, 80)

    def test_stitch_dedup_and_order(self):
        h = [Candle(at(9, 15), 1, 1, 1, 1, 10), Candle(at(9, 20), 2, 2, 2, 2, 10)]
        live = [Candle(at(9, 20), 2, 3, 2, 3, 99)]
        cur = Candle(at(9, 25), 3, 3, 3, 3, 1)
        out = stitch(h, live, cur)
        self.assertEqual([c.ts for c in out], [at(9, 15), at(9, 20), at(9, 25)])
        self.assertEqual(out[1].volume, 99)

    def test_resample_and_gaps(self):
        one = [Candle(at(9, 15) + timedelta(minutes=i), 100 + i, 101 + i, 99 + i, 100.5 + i, 10) for i in range(10)]
        five = resample_candles(one, 5)
        self.assertEqual(len(five), 2)
        self.assertEqual((five[0].open, five[0].close, five[0].high, five[0].low, five[0].volume),
                         (100, 104.5, 105, 99, 50))
        ts = [at(9, 15), at(9, 20), at(9, 30)]
        gaps = find_gaps(ts, 5, session_close=time(9, 35))
        self.assertEqual(gaps, [at(9, 25)])

    def test_heikin_ashi_first_bar(self):
        df = pd.DataFrame({"open": [10.0, 11], "high": [12.0, 13], "low": [9.0, 10], "close": [11.0, 12]})
        ha = heikin_ashi(df)
        self.assertEqual(ha["close"].iloc[0], (10 + 12 + 9 + 11) / 4)
        self.assertEqual(ha["open"].iloc[0], 10.5)
        self.assertEqual(ha["open"].iloc[1], (ha["open"].iloc[0] + ha["close"].iloc[0]) / 2)


if __name__ == "__main__":
    unittest.main()
