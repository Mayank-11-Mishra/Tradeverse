import unittest
from datetime import time

import numpy as np
import pandas as pd

from app.backtesting.engine import (BacktestConfig, ChargeModel, Strategy, compute_metrics,
                                    optimize, run_backtest, Trade)


def bars(rows, start="2025-01-01 09:15", freq="5min"):
    """rows: list of (open, high, low, close)"""
    idx = pd.date_range(start, periods=len(rows), freq=freq)
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx).assign(volume=100.0)


ZERO = BacktestConfig(slippage_bps=0, charges=ChargeModel.zero(), max_leverage=1000)


class BuyOnce(Strategy):
    def __init__(self, at=0, side="BUY", qty=10, **kw):
        super().__init__(**kw)
        self.at, self.side, self.qty, self.kw = at, side, qty, {k: v for k, v in kw.items()}
        self.done = False

    def on_bar(self, ctx):
        if ctx.i == self.at and not self.done:
            self.done = True
            (ctx.buy if self.side == "BUY" else ctx.sell)(self.qty, **self.kw)


class TestFillTiming(unittest.TestCase):
    def test_signal_fills_next_bar_open_not_signal_bar(self):
        d = bars([(100, 101, 99, 100), (110, 111, 109, 110), (120, 121, 119, 120)])
        r = run_backtest(d, BuyOnce(at=0), ZERO)
        t = r.trades[0]
        self.assertEqual(t.entry_price, 110)            # bar 1 open, not bar 0 close (100)
        self.assertEqual(t.exit_reason, "end_of_data")
        self.assertEqual(t.exit_price, 120)
        self.assertAlmostEqual(t.net_pnl, 100)

    def test_strategy_cannot_see_future_bars(self):
        seen = []

        class Spy(Strategy):
            def on_bar(self, ctx):
                seen.append((ctx.i, len(ctx.history())))
        run_backtest(bars([(1, 2, 0.5, 1)] * 5), Spy(), ZERO)
        for i, n in seen:
            self.assertEqual(n, i + 1)


class TestStops(unittest.TestCase):
    def test_stop_loss_hit_intrabar(self):
        d = bars([(100, 100, 100, 100), (100, 101, 94, 96), (96, 97, 95, 96)])
        r = run_backtest(d, BuyOnce(at=0, stop_loss=95), ZERO)
        t = r.trades[0]
        self.assertEqual((t.exit_reason, t.exit_price), ("stop_loss", 95))
        self.assertAlmostEqual(t.net_pnl, -50)

    def test_gap_through_stop_fills_at_open(self):
        d = bars([(100, 100, 100, 100), (100, 100, 100, 100), (90, 91, 89, 90)])
        r = run_backtest(d, BuyOnce(at=0, stop_loss=95), ZERO)
        self.assertEqual(r.trades[0].exit_price, 90)

    def test_take_profit(self):
        d = bars([(100, 100, 100, 100), (100, 106, 99, 105), (105, 105, 105, 105)])
        r = run_backtest(d, BuyOnce(at=0, take_profit=105), ZERO)
        self.assertEqual((r.trades[0].exit_reason, r.trades[0].exit_price), ("take_profit", 105))

    def test_stop_wins_when_both_hit_same_bar(self):
        d = bars([(100, 100, 100, 100), (100, 110, 90, 100), (100, 100, 100, 100)])
        r = run_backtest(d, BuyOnce(at=0, stop_loss=95, take_profit=105), ZERO)
        self.assertEqual(r.trades[0].exit_reason, "stop_loss")

    def test_short_stop_and_pct_stops(self):
        d = bars([(100, 100, 100, 100), (100, 106, 99, 105), (105, 105, 105, 105)])
        r = run_backtest(d, BuyOnce(at=0, side="SELL", sl_pct=0.05), ZERO)
        t = r.trades[0]
        self.assertEqual(t.side, "SHORT")
        self.assertEqual((t.exit_reason, round(t.exit_price, 6)), ("stop_loss", 105.0))

    def test_trailing_stop_ratchets_up(self):
        rows = [(100, 100, 100, 100), (100, 100, 100, 100),     # entry at bar1 open=100
                (100, 120, 100, 120),                            # peak 120 -> trail 10% = 108 (applies from next bar)
                (118, 119, 107, 108), (108, 108, 108, 108)]
        r = run_backtest(bars(rows), BuyOnce(at=0, trail_pct=0.10), ZERO)
        t = r.trades[0]
        self.assertEqual(t.exit_reason, "stop_loss")
        self.assertAlmostEqual(t.exit_price, 108.0)


class TestCostsAndRisk(unittest.TestCase):
    def test_slippage_is_adverse(self):
        d = bars([(100, 100, 100, 100), (100, 100, 100, 100), (100, 100, 100, 100)])
        cfg = BacktestConfig(slippage_bps=10, charges=ChargeModel.zero(), max_leverage=1000)
        t = run_backtest(d, BuyOnce(at=0), cfg).trades[0]
        self.assertAlmostEqual(t.entry_price, 100.1)
        self.assertLess(t.net_pnl, 0)

    def test_charges_reduce_net_pnl(self):
        d = bars([(100, 100, 100, 100), (100, 100, 100, 100), (100, 100, 100, 100)])
        cfg = BacktestConfig(slippage_bps=0, max_leverage=1000)
        t = run_backtest(d, BuyOnce(at=0, qty=100), cfg).trades[0]
        self.assertEqual(t.gross_pnl, 0)
        self.assertGreater(t.charges, 0)
        self.assertAlmostEqual(t.net_pnl, -t.charges)

    def test_charge_model_components(self):
        c = ChargeModel(brokerage_flat=20, brokerage_pct=0.0003, stt_sell_pct=0.001, exch_txn_pct=0,
                        sebi_pct=0, stamp_buy_pct=0, gst_pct=0.18)
        # turnover 10000: brokerage min(20, 3)=3, gst .54, stt on sell 10
        self.assertAlmostEqual(c.charges("BUY", 100, 100), 3.54)
        self.assertAlmostEqual(c.charges("SELL", 100, 100), 13.54)

    def test_leverage_rejection(self):
        d = bars([(100, 100, 100, 100)] * 4)
        cfg = BacktestConfig(initial_capital=1000, slippage_bps=0, charges=ChargeModel.zero(), max_leverage=1)
        r = run_backtest(d, BuyOnce(at=0, qty=100), cfg)  # notional 10000 > 1000
        self.assertEqual(len(r.trades), 0)
        self.assertEqual(r.rejected_orders[0]["reason"], "exceeds max_leverage")

    def test_short_disabled(self):
        d = bars([(100, 100, 100, 100)] * 4)
        cfg = BacktestConfig(slippage_bps=0, charges=ChargeModel.zero(), allow_short=False)
        r = run_backtest(d, BuyOnce(at=0, side="SELL"), cfg)
        self.assertEqual(len(r.trades), 0)
        self.assertEqual(len(r.rejected_orders), 1)

    def test_squareoff_flattens_and_blocks_reentry(self):
        idx = pd.to_datetime(["2025-01-01 15:05", "2025-01-01 15:10", "2025-01-01 15:15",
                              "2025-01-01 15:20", "2025-01-02 09:15", "2025-01-02 09:20"])
        d = pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1.0}, index=idx)

        class Always(Strategy):
            def on_bar(self, ctx):
                if ctx.position == 0:
                    ctx.buy(1)
        r = run_backtest(d, Always(), BacktestConfig(slippage_bps=0, charges=ChargeModel.zero(),
                                                     squareoff_time=time(15, 15)))
        reasons = [t.exit_reason for t in r.trades]
        self.assertIn("squareoff", reasons)
        sq = [t for t in r.trades if t.exit_reason == "squareoff"][0]
        self.assertEqual(pd.Timestamp(sq.exit_time), pd.Timestamp("2025-01-01 15:15"))
        # no entry between squareoff and next day
        for t in r.trades:
            self.assertFalse(pd.Timestamp("2025-01-01 15:15") < pd.Timestamp(t.entry_time) <= pd.Timestamp("2025-01-01 15:20"))

    def test_flip_long_to_short(self):
        d = bars([(100, 100, 100, 100), (100, 100, 100, 100), (110, 110, 110, 110), (120, 120, 120, 120)])

        class Flip(Strategy):
            def on_bar(self, ctx):
                if ctx.i == 0:
                    ctx.buy(10)
                if ctx.i == 1:
                    ctx.sell(20)
        r = run_backtest(d, Flip(), ZERO)
        self.assertEqual([t.side for t in r.trades], ["LONG", "SHORT"])
        self.assertAlmostEqual(r.trades[0].net_pnl, 100)      # 10*(110-100)
        self.assertAlmostEqual(r.trades[1].net_pnl, -100)     # short 10 @110 closed @120

    def test_bad_data_rejected(self):
        d = bars([(1, 1, 1, 1)] * 3)
        with self.assertRaises(ValueError):
            run_backtest(d.iloc[::-1], BuyOnce(), ZERO)
        with self.assertRaises(ValueError):
            run_backtest(d.drop(columns=["close"]), BuyOnce(), ZERO)


class TestMetrics(unittest.TestCase):
    def test_metrics_hand_calc(self):
        def tr(p, m):
            return Trade(pd.Timestamp(f"2025-{m:02d}-01"), pd.Timestamp(f"2025-{m:02d}-02"), "LONG", 1, 1, 1, p, 0, p, "x")
        trades = [tr(100, 1), tr(50, 1), tr(-30, 2), tr(-20, 2), tr(10, 3)]
        eq = pd.Series([1000, 1100, 1150, 1120, 1100, 1110],
                       index=pd.date_range("2025-01-01", periods=6, freq="D"))
        m = compute_metrics(trades, eq, 1000)
        self.assertEqual(m["total_trades"], 5)
        self.assertEqual(m["winning_trades"], 3)
        self.assertAlmostEqual(m["win_rate_pct"], 60)
        self.assertAlmostEqual(m["profit_factor"], 160 / 50)
        self.assertAlmostEqual(m["max_drawdown"], -50)
        self.assertEqual(m["max_consecutive_wins"], 2)
        self.assertEqual(m["max_consecutive_losses"], 2)
        self.assertAlmostEqual(m["expectancy"], 22.0)
        self.assertEqual(m["monthly_pnl"], {"2025-01": 150, "2025-02": -50, "2025-03": 10})
        self.assertAlmostEqual(m["net_profit"], 110)

    def test_no_trades(self):
        eq = pd.Series([1000.0, 1000.0], index=pd.date_range("2025-01-01", periods=2, freq="D"))
        m = compute_metrics([], eq, 1000)
        self.assertEqual(m["total_trades"], 0)
        self.assertIsNone(m["profit_factor"])


class EmaCross(Strategy):
    def on_bar(self, ctx):
        f, s = ctx.ind("ema", length=self.params.get("fast", 5)), ctx.ind("ema", length=self.params.get("slow", 20))
        pf, ps = ctx.ind("ema", shift=1, length=self.params.get("fast", 5)), ctx.ind("ema", shift=1, length=self.params.get("slow", 20))
        if any(np.isnan([f, s, pf, ps])):
            return
        if pf <= ps and f > s and ctx.position <= 0:
            ctx.buy(10 + (-ctx.position))
        elif pf >= ps and f < s and ctx.position >= 0:
            ctx.sell(10 + ctx.position)


class TestIntegration(unittest.TestCase):
    def _data(self):
        rng = np.random.default_rng(3)
        n = 800
        idx = pd.date_range("2025-01-01 09:15", periods=n, freq="15min")
        c = 100 + np.cumsum(rng.normal(0, 0.4, n))
        return pd.DataFrame({"open": c, "high": c + 0.3, "low": c - 0.3, "close": c, "volume": 100.0}, index=idx)

    def test_ema_cross_runs_and_is_consistent(self):
        r = run_backtest(self._data(), EmaCross(), BacktestConfig(slippage_bps=1))
        self.assertGreater(len(r.trades), 5)
        net = sum(t.net_pnl for t in r.trades)
        self.assertAlmostEqual(net, r.equity.iloc[-1] - 100_000, places=6)   # equity reconciles with trades
        self.assertAlmostEqual(r.metrics["net_profit"], net, places=6)

    def test_deterministic(self):
        d = self._data()
        a = run_backtest(d, EmaCross()).metrics["net_profit"]
        b = run_backtest(d, EmaCross()).metrics["net_profit"]
        self.assertEqual(a, b)

    def test_optimize_sorted(self):
        res = optimize(self._data(), EmaCross, {"fast": [3, 5], "slow": [15, 30]})
        vals = [m["net_profit"] for _, m in res]
        self.assertEqual(vals, sorted(vals, reverse=True))
        self.assertEqual(len(res), 4)


if __name__ == "__main__":
    unittest.main()
