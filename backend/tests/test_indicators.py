import unittest

import numpy as np
import pandas as pd

from app.indicators import engine as ind


def make_df(n=300, seed=7):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01 09:15", periods=n, freq="5min")
    close = 100 + np.cumsum(rng.normal(0, 0.5, n))
    open_ = close + rng.normal(0, 0.1, n)
    high = np.maximum(open_, close) + rng.uniform(0, 0.4, n)
    low = np.minimum(open_, close) - rng.uniform(0, 0.4, n)
    vol = rng.integers(100, 1000, n).astype(float)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)


class TestKnownValues(unittest.TestCase):
    def test_sma_hand_values(self):
        s = pd.Series([1.0, 2, 3, 4, 5])
        out = ind.sma(s, 3)
        self.assertTrue(np.isnan(out.iloc[1]))
        self.assertEqual(list(out.iloc[2:]), [2.0, 3.0, 4.0])

    def test_ema_hand_values(self):
        s = pd.Series([1.0, 2, 3, 4, 5])
        out = ind.ema(s, 3)  # seed=2, k=0.5 -> 3, 4
        self.assertEqual(list(out.iloc[2:]), [2.0, 3.0, 4.0])

    def test_wma(self):
        out = ind.wma(pd.Series([1.0, 2, 3]), 3)
        self.assertAlmostEqual(out.iloc[2], (1 * 1 + 2 * 2 + 3 * 3) / 6)

    def test_rsi_matches_reference_wilder(self):
        df = make_df()
        c = df["close"].to_numpy()
        n = 14
        d = np.diff(c)
        g, l = np.clip(d, 0, None), np.clip(-d, 0, None)
        ag, al = g[:n].mean(), l[:n].mean()
        ref = {n: 100 - 100 / (1 + ag / al)}
        for i in range(n, len(d)):
            ag = (ag * (n - 1) + g[i]) / n
            al = (al * (n - 1) + l[i]) / n
            ref[i + 1] = 100 - 100 / (1 + ag / al)
        out = ind.rsi(df["close"], n)
        for i, v in ref.items():
            self.assertAlmostEqual(out.iloc[i], v, places=9)
        self.assertTrue(out.iloc[:n].isna().all())

    def test_rsi_monotonic_up_is_100(self):
        out = ind.rsi(pd.Series(np.arange(1.0, 40.0)), 14)
        self.assertEqual(out.iloc[-1], 100.0)

    def test_atr_first_value_is_mean_true_range(self):
        df = make_df()
        tr = ind.true_range(df)
        self.assertAlmostEqual(ind.atr(df, 14).iloc[13], tr.iloc[:14].mean())

    def test_macd_identity(self):
        df = make_df()
        m = ind.macd(df["close"])
        d = (m["macd"] - m["signal"] - m["hist"]).dropna()
        self.assertTrue((d.abs() < 1e-12).all())

    def test_bbands_width(self):
        df = make_df()
        b = ind.bbands(df["close"], 20, 2.0)
        sd = df["close"].rolling(20).std(ddof=0)
        self.assertAlmostEqual((b["upper"] - b["lower"]).iloc[-1], 4 * sd.iloc[-1])

    def test_stoch_bounds(self):
        s = ind.stoch(make_df()).dropna()
        self.assertTrue(((s["k"] >= 0) & (s["k"] <= 100)).all())

    def test_adx_bounds(self):
        a = ind.adx(make_df()).dropna()
        self.assertTrue(((a["adx"] >= 0) & (a["adx"] <= 100)).all())

    def test_obv_manual(self):
        df = pd.DataFrame({"close": [10, 11, 10, 10], "volume": [5, 7, 3, 9]}, dtype=float)
        self.assertEqual(list(ind.obv(df)), [0, 7, 4, 4])

    def test_donchian(self):
        df = make_df()
        d = ind.donchian(df, 10)
        self.assertAlmostEqual(d["upper"].iloc[-1], df["high"].iloc[-10:].max())

    def test_vwap_resets_each_day(self):
        idx = pd.to_datetime(["2025-01-01 09:15", "2025-01-01 09:20", "2025-01-02 09:15"])
        df = pd.DataFrame({"open": 1.0, "high": [10, 20, 30], "low": [10, 20, 30],
                           "close": [10, 20, 30], "volume": [1, 1, 1]}, index=idx).astype(float)
        v = ind.vwap(df)
        self.assertEqual(list(v), [10.0, 15.0, 30.0])

    def test_vwap_nan_for_zero_volume(self):
        df = make_df(10)
        df["volume"] = 0.0
        self.assertTrue(ind.vwap(df).isna().all())

    def test_pivot_uses_previous_day(self):
        daily = pd.DataFrame({"high": [110.0, 120], "low": [90.0, 100], "close": [100.0, 110]})
        p = ind.pivot_points(daily)
        self.assertTrue(np.isnan(p["pivot"].iloc[0]))
        self.assertAlmostEqual(p["pivot"].iloc[1], 100.0)
        self.assertAlmostEqual(p["r1"].iloc[1], 110.0)
        self.assertAlmostEqual(p["s1"].iloc[1], 90.0)

    def test_supertrend_flips_on_reversal(self):
        up = np.linspace(100, 160, 60)
        down = np.linspace(160, 90, 60)
        close = np.concatenate([up, down])
        df = pd.DataFrame({"open": close, "high": close + 0.5, "low": close - 0.5,
                           "close": close, "volume": 100.0},
                          index=pd.date_range("2025-01-01", periods=len(close), freq="D"))
        st = ind.supertrend(df, 10, 3.0)
        self.assertEqual(st["direction"].iloc[55], 1.0)
        self.assertEqual(st["direction"].iloc[-1], -1.0)
        # line sits below price in uptrend, above in downtrend
        self.assertLess(st["supertrend"].iloc[55], close[55])
        self.assertGreater(st["supertrend"].iloc[-1], close[-1])

    def test_psar_below_price_in_uptrend(self):
        close = np.linspace(100, 150, 50)
        df = pd.DataFrame({"high": close + 0.5, "low": close - 0.5, "close": close, "open": close, "volume": 1.0})
        s = ind.psar(df)
        self.assertLess(s.iloc[-1], df["low"].iloc[-1])

    def test_crossovers(self):
        a = pd.Series([1.0, 2, 3, 2, 1])
        b = pd.Series([2.0, 2, 2, 2, 2])
        self.assertEqual(list(ind.crossed_above(a, b)), [False, False, True, False, False])
        self.assertEqual(list(ind.crossed_below(a, b)), [False, False, False, False, True])


class TestRegistryAndCausality(unittest.TestCase):
    def test_every_indicator_computes(self):
        df = make_df()
        for name in ind.REGISTRY:
            out = ind.compute_indicator(name, df)
            self.assertEqual(len(out), len(df), name)
            self.assertTrue(out.iloc[-1].notna().all(), f"{name} last row has NaN")

    def test_causality(self):
        """Indicator values must not change when future bars are appended."""
        df = make_df(260)
        cut = 200
        for name in ind.REGISTRY:
            full = ind.compute_indicator(name, df)
            part = ind.compute_indicator(name, df.iloc[:cut])
            a, b = full.iloc[:cut].to_numpy(), part.to_numpy()
            np.testing.assert_allclose(a, b, rtol=1e-9, atol=1e-9, equal_nan=True, err_msg=name)

    def test_unknown_indicator_and_params(self):
        df = make_df(50)
        with self.assertRaises(KeyError):
            ind.compute_indicator("nope", df)
        with self.assertRaises(ValueError):
            ind.compute_indicator("sma", df, bogus=1)


if __name__ == "__main__":
    unittest.main()
