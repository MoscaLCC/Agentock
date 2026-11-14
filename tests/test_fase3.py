"""Testes dos agentes de script da Fase 3 (sem rede)."""
import importlib.util
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from core.data.providers.regulators import SEC
from core.sessions import build_proxies, compute_lead, proxy_move

ROOT = Path(__file__).resolve().parent.parent


def load(agent: str):
    spec = importlib.util.spec_from_file_location(f"_t3_{agent}", ROOT / "agents" / agent / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def bars(times_prices):
    return [{"t": t, "c": p} for t, p in times_prices]


class SessionTests(unittest.TestCase):
    CLOSE = "2026-11-13T08:00:00+00:00"  # fecho de Hong Kong

    def test_proxy_move(self):
        b = bars([("2026-11-13T07:55:00Z", 100), ("2026-11-13T14:30:00Z", 101), ("2026-11-13T20:55:00Z", 103)])
        m = proxy_move(b, self.CLOSE)
        self.assertAlmostEqual(m["change_pct"], 3.0)
        self.assertIsNone(proxy_move(bars([("2026-11-13T07:00:00Z", 100)]), self.CLOSE))  # nada depois do fecho

    def test_us_lead_for_hk_stock(self):
        prof = {"cross_listings": [{"symbol": "BABA", "market": "US"}, {"symbol": "AHLA.DE", "market": "EU"}]}
        px = build_proxies("us", prof)
        self.assertEqual([p["kind"] for p in px][:2], ["cross_listing", "future"])
        moves = {"BABA": 2.0, "ES=F": 0.5, "NQ=F": 0.7, "^GSPC": 0.4, "^IXIC": 0.6}
        for p in px:
            p["move"] = {"change_pct": moves[p["symbol"]]}
        state = {"known": True, "open": False, "last_close": self.CLOSE}
        out = compute_lead("us", "HK", state, px, datetime(2026, 11, 14, tzinfo=timezone.utc))
        self.assertTrue(out["applicable"])
        self.assertEqual(out["bias"], "positivo")
        self.assertGreater(out["confidence"], 0.6)

    def test_not_applicable_cases(self):
        st = {"known": True, "open": False, "last_close": self.CLOSE}
        self.assertFalse(compute_lead("asia", "HK", st, [], datetime.now(timezone.utc))["applicable"])
        self.assertFalse(compute_lead("us", "HK", {**st, "open": True}, [], datetime.now(timezone.utc))["applicable"])
        out = compute_lead("europe", "US", st, [{"symbol": "^GDAXI", "kind": "index", "move": None}],
                           datetime.now(timezone.utc))
        self.assertIn("nenhum proxy", out["reason"])


FIN = {
    "fiscal_years": [2025, 2024],
    "income": {"revenue": [120, 100], "gross_profit": [60, 45], "net_income": [12, 8], "ebit": [18, 12],
               "ebitda": [25, 18], "operating_income": [18, 12], "interest_expense": [2, 2]},
    "balance": {"total_assets": [200, 190], "total_liabilities": [90, 95], "current_assets": [80, 70],
                "current_liabilities": [40, 40], "long_term_debt": [30, 35], "total_debt": [40, 45], "cash": [20, 15],
                "retained_earnings": [70, 60], "shares": [10, 10], "working_capital": [40, 30]},
    "cashflow": {"operating_cash_flow": [20, 15], "free_cash_flow": [14, 10]},
    "ratios": {"roe": 0.12, "operating_margin": 0.15, "debt_to_equity": 36.4, "beta": 1.1, "market_cap": 300,
               "trailing_pe": 25.0},
    "shares": {"outstanding": 10},
}


class HealthFundamentalTests(unittest.TestCase):
    def test_piotroski_and_altman(self):
        m = load("health_momentum_agent")
        pio = m.piotroski(FIN)
        self.assertEqual((pio["points"], pio["available"]), (9, 9))
        alt = m.altman(FIN, 300, "Technology")
        self.assertEqual(alt["zone"], "segura")
        sc = m.scores(FIN, pio, alt, {"relative_pp": {"3m": 5, "6m": 10, "12m": -5}})
        self.assertEqual(sc["health_score"], 100)
        self.assertEqual(sc["momentum_score"], 58)

    def test_dcf_and_analysis(self):
        m = load("fundamental_data_agent")
        out = m.analyse(FIN, price=30.0)
        self.assertEqual(out["growth"]["revenue_yoy_pct"], 20.0)
        self.assertEqual(out["balance"]["net_debt"], 20)
        self.assertIsNotNone(out["dcf"]["value_per_share"])
        self.assertEqual(out["dcf"]["assumptions"]["growth_1_5"], 15.0)  # CAGR 20% limitado a 15%
        comps = {"medians": {"trailing_pe": 20.0}}
        self.assertEqual(m.analyse(FIN, 30.0, comps=comps)["vs_peers"]["trailing_pe"], 25.0)


class IpoTests(unittest.TestCase):
    def test_calendar_filters_spacs_small_and_dedupes(self):
        m = load("ipo_calendar_agent")
        items = [
            {"date": "2026-11-19", "symbol": "ANT", "name": "ANTHROPIC, PBC", "value": 7.4e10, "price_range": "70.00-78.00"},
            {"date": "2026-11-19", "symbol": "ANT", "name": "Anthropic PBC", "exchange": "NASDAQ"},
            {"date": "2026-11-16", "symbol": "BRRK", "name": "Bluerock Acquisition Corp. II"},
            {"date": "2026-11-20", "symbol": "SML", "name": "Small Co", "shares": 1e6, "price_range": "10-12"},
            {"date": "2026-11-21", "symbol": None, "name": "Unknown Size Ltd"},
        ]
        out = m.normalize(items, 5e8, False)
        self.assertEqual([i["symbol"] for i in out["ipos"]], ["ANT", None])
        self.assertEqual(out["ipos"][0]["exchange"], "NASDAQ")  # informação juntada
        self.assertEqual(out["excluded"], {"spacs": 1, "below_threshold": 1})

    def test_lifecycle_events(self):
        m = load("ipo_lifecycle_agent")
        ev = m.events(date(2026, 6, 1), "US", 180, True)
        self.assertEqual([e["type"] for e in ev], ["ipo_debut", "quiet_period_end", "lockup_expiry", "ipo_anniversary"])
        self.assertEqual(ev[2]["date"], "2026-11-28")
        oh = m.overhang(100e6, 20e6, [{"v": 2e6}] * 20)
        self.assertEqual(oh["days_to_trade_locked"], 40.0)

    def test_lockup_parse(self):
        text = ("Our officers and directors have agreed, for a period of 180 days after the date of this prospectus, "
                "not to sell. The lock-up period ends 180 days after the date of this prospectus.")
        self.assertEqual(SEC.parse_lockup(text)["days"], 180)
        self.assertIsNone(SEC.parse_lockup("nothing here"))


if __name__ == "__main__":
    unittest.main()
