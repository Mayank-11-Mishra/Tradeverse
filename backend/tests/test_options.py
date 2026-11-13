import unittest
from datetime import date, datetime
from math import exp

from app.option_chain import analytics as oa


class TestBlackScholes(unittest.TestCase):
    S, K, T, r, s = 100.0, 100.0, 1.0, 0.05, 0.20

    def test_reference_prices(self):
        # Hull textbook values for S=K=100,T=1,r=5%,vol=20%
        self.assertAlmostEqual(oa.bs_price("CE", self.S, self.K, self.T, self.r, self.s), 10.4506, places=3)
        self.assertAlmostEqual(oa.bs_price("PE", self.S, self.K, self.T, self.r, self.s), 5.5735, places=3)

    def test_put_call_parity(self):
        for K in (80, 100, 120):
            c = oa.bs_price("CE", 100, K, 0.5, 0.06, 0.25, 0.01)
            p = oa.bs_price("PE", 100, K, 0.5, 0.06, 0.25, 0.01)
            self.assertAlmostEqual(c - p, 100 * exp(-0.01 * 0.5) - K * exp(-0.06 * 0.5), places=8)

    def test_greeks_reference(self):
        g = oa.greeks("CE", self.S, self.K, self.T, self.r, self.s)
        self.assertAlmostEqual(g.delta, 0.6368, places=3)
        self.assertAlmostEqual(g.gamma, 0.018762, places=5)
        self.assertAlmostEqual(g.vega, 0.37524, places=4)           # per 1 vol pt
        self.assertAlmostEqual(g.theta * 365, -6.4140, places=2)    # annual theta
        gp = oa.greeks("PE", self.S, self.K, self.T, self.r, self.s)
        self.assertAlmostEqual(g.delta - gp.delta, 1.0, places=8)   # call delta - put delta = e^{-qT}
        self.assertAlmostEqual(g.gamma, gp.gamma, places=10)

    def test_greeks_match_finite_differences(self):
        h = 0.01
        up = oa.bs_price("CE", 100 + h, 105, 0.3, 0.06, 0.22)
        dn = oa.bs_price("CE", 100 - h, 105, 0.3, 0.06, 0.22)
        mid = oa.bs_price("CE", 100, 105, 0.3, 0.06, 0.22)
        g = oa.greeks("CE", 100, 105, 0.3, 0.06, 0.22)
        self.assertAlmostEqual(g.delta, (up - dn) / (2 * h), places=5)
        self.assertAlmostEqual(g.gamma, (up - 2 * mid + dn) / h ** 2, places=3)
        dv = 1e-4
        v = (oa.bs_price("CE", 100, 105, 0.3, 0.06, 0.22 + dv) - oa.bs_price("CE", 100, 105, 0.3, 0.06, 0.22 - dv)) / (2 * dv)
        self.assertAlmostEqual(g.vega * 100, v, places=4)

    def test_expired_option_intrinsic(self):
        self.assertEqual(oa.bs_price("CE", 105, 100, 0, 0.05, 0.2), 5)
        self.assertEqual(oa.greeks("PE", 95, 100, 0, 0.05, 0.2).delta, -1.0)


class TestImpliedVol(unittest.TestCase):
    def test_roundtrip(self):
        for kind in ("CE", "PE"):
            for sigma in (0.08, 0.2, 0.6, 1.5):
                p = oa.bs_price(kind, 22000, 22200, 7 / 365, 0.07, sigma)
                iv = oa.implied_vol(kind, p, 22000, 22200, 7 / 365, 0.07)
                self.assertIsNotNone(iv)
                self.assertAlmostEqual(iv, sigma, places=5)

    def test_invalid_prices_return_none(self):
        self.assertIsNone(oa.implied_vol("CE", 0.0, 100, 100, 0.1, 0.05))
        self.assertIsNone(oa.implied_vol("CE", 1.0, 100, 50, 0.1, 0.05))      # below intrinsic
        self.assertIsNone(oa.implied_vol("CE", 150.0, 100, 100, 0.1, 0.05))   # above spot
        self.assertIsNone(oa.implied_vol("CE", 5.0, 100, 100, 0.0, 0.05))     # expired


class TestTime(unittest.TestCase):
    def test_time_to_expiry(self):
        from datetime import timezone
        now = datetime(2025, 1, 1, 15, 30, tzinfo=oa.IST)
        self.assertAlmostEqual(oa.time_to_expiry(now, date(2025, 1, 8)) * 365, 7.0, places=9)
        self.assertEqual(oa.time_to_expiry(now, date(2024, 12, 1)), 0.0)
        with self.assertRaises(ValueError):
            oa.time_to_expiry(datetime(2025, 1, 1), date(2025, 1, 8))


class TestChainStats(unittest.TestCase):
    def test_pcr(self):
        self.assertAlmostEqual(oa.pcr({1: 30, 2: 20}, {1: 10, 2: 15}), 2.0)
        self.assertIsNone(oa.pcr({1: 5}, {}))

    def test_max_pain_hand_calc(self):
        calls = {100: 10, 110: 10, 120: 10}
        puts = {100: 10, 110: 10, 120: 10}
        # symmetric OI -> pain minimised at the middle strike
        self.assertEqual(oa.max_pain(calls, puts), 110)
        # heavy put OI at 100 pulls max pain downwards to 100
        self.assertEqual(oa.max_pain({100: 1, 110: 1}, {100: 1000}), 100)

    def test_buildup(self):
        self.assertEqual(oa.oi_buildup(1, 5), "long_buildup")
        self.assertEqual(oa.oi_buildup(-1, 5), "short_buildup")
        self.assertEqual(oa.oi_buildup(1, -5), "short_covering")
        self.assertEqual(oa.oi_buildup(-1, -5), "long_unwinding")
        self.assertEqual(oa.oi_buildup(0, 5), "neutral")

    def test_moneyness_and_atm(self):
        self.assertEqual(oa.moneyness("CE", 100, 105), "ITM")
        self.assertEqual(oa.moneyness("PE", 100, 105), "OTM")
        self.assertEqual(oa.moneyness("CE", 105, 105), "ATM")
        self.assertEqual(oa.atm_strike(103, [90, 100, 105, 110]), 105)


def flat_prices(kind, strike):
    # simple synthetic premium table for template geometry tests
    return {("CE", 100): 10, ("PE", 100): 10, ("CE", 110): 4, ("PE", 90): 4,
            ("CE", 120): 1, ("PE", 80): 1, ("CE", 90): 16, ("PE", 110): 16}[(kind, strike)]


class TestPayoff(unittest.TestCase):
    def test_long_call(self):
        s = oa.analyze_payoff(oa.build_template("long_call", 100, 10, flat_prices, 1))
        self.assertEqual(s.breakevens, [110.0])
        self.assertIsNone(s.max_profit)
        self.assertEqual(s.max_loss, -10)

    def test_short_straddle(self):
        legs = oa.build_template("short_straddle", 100, 10, flat_prices, 50)
        s = oa.analyze_payoff(legs)
        self.assertEqual(s.breakevens, [80.0, 120.0])
        self.assertEqual(s.max_profit, 20 * 50)
        self.assertIsNone(s.max_loss)

    def test_bull_call_spread(self):
        s = oa.analyze_payoff(oa.build_template("bull_call_spread", 100, 10, flat_prices, 1))
        self.assertEqual(s.breakevens, [106.0])
        self.assertEqual(s.max_profit, 4)    # width 10 - debit 6
        self.assertEqual(s.max_loss, -6)

    def test_iron_condor(self):
        legs = oa.build_template("iron_condor", 100, 10, flat_prices, 1, width=1)
        # +PE80 -PE90 -CE110 +CE120 : credit = 4+4-1-1 = 6
        s = oa.analyze_payoff(legs)
        self.assertAlmostEqual(s.max_profit, 6)
        self.assertAlmostEqual(s.max_loss, -4)   # wing 10 - credit 6
        self.assertEqual(s.breakevens, [84.0, 116.0])

    def test_long_butterfly(self):
        def pr(kind, k):
            return {90: 16, 100: 10, 110: 4}[k]
        s = oa.analyze_payoff(oa.build_template("long_butterfly", 100, 10, pr, 1))
        self.assertEqual(s.max_loss, -(16 - 20 + 4))  # net debit = 0 -> -0 ; check below
        self.assertEqual(s.max_profit, 10 - 0)

    def test_future_leg_slope(self):
        s = oa.analyze_payoff([oa.Leg("FUT", 100, 0, 10)])
        self.assertIsNone(s.max_profit)
        self.assertEqual(s.breakevens, [100.0])

    def test_payoff_matches_sampling(self):
        legs = oa.build_template("iron_condor", 100, 10, flat_prices, 1)
        curve = oa.payoff_curve(legs, 50, 150, 1001)
        self.assertAlmostEqual(max(v for _, v in curve), oa.analyze_payoff(legs).max_profit)
        self.assertAlmostEqual(min(v for _, v in curve), oa.analyze_payoff(legs).max_loss)

    def test_unknown_template(self):
        with self.assertRaises(KeyError):
            oa.build_template("nope", 100, 10, flat_prices, 1)


if __name__ == "__main__":
    unittest.main()
