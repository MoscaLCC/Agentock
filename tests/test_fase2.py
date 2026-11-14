"""Testes dos agentes de script da Fase 2 (sem rede)."""
import importlib.util
import math
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(agent: str):
    spec = importlib.util.spec_from_file_location(f"_t_{agent}", ROOT / "agents" / agent / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def bars(n: int, start: float = 100.0, drift: float = 0.002):
    out, p, d0 = [], start, date(2025, 1, 1)
    for i in range(n):
        p *= 1 + drift + 0.01 * math.sin(i / 3)
        out.append({"t": (d0 + timedelta(days=i)).isoformat(), "o": p * 0.99, "h": p * 1.01, "l": p * 0.98,
                    "c": p, "v": 1000 + 10 * i})
    return out


class IndicatorTests(unittest.TestCase):
    def setUp(self):
        self.m = load("technical_indicators_agent")

    def test_full_history(self):
        out = self.m.compute(bars(400), "AAPL")
        self.assertTrue(out["available"])
        self.assertIsNotNone(out["sma200"])
        self.assertEqual(out["trend"]["label"], "alta")
        self.assertIsNone(out["price_limit"])
        self.assertTrue(0 <= out["rsi14"] <= 100)

    def test_short_history_ipo(self):
        out = self.m.compute(bars(60), "300750.SZ")
        self.assertIsNone(out["sma200"])
        self.assertTrue(any("SMA200" in x for x in out["limitations"]))
        self.assertEqual(out["price_limit"]["limit_pct"], 20.0)  # ChiNext

    def test_daily_limits(self):
        self.assertEqual(self.m.daily_limit_pct("600519.SS"), 10.0)
        self.assertEqual(self.m.daily_limit_pct("688981.SS"), 20.0)
        self.assertEqual(self.m.daily_limit_pct("005930.KS"), 30.0)
        self.assertIsNone(self.m.daily_limit_pct("AAPL"))


class CalendarAnalystTargetTests(unittest.TestCase):
    def test_calendar(self):
        m = load("calendar_agent")
        today = date(2026, 11, 14)
        out = m.build({"earnings_dates": ["2026-11-20"], "ex_dividend": "2026-11-12"},
                      {"events": [{"date": "2027-05-01", "type": "lockup", "label": "Fim do lock-up", "confirmed": False}]},
                      today)
        self.assertEqual(out["days_to_earnings"], 6)
        self.assertTrue(out["earnings_within_14d"])
        self.assertEqual([e["type"] for e in out["upcoming"]], ["earnings", "lockup"])

    def test_analysts(self):
        m = load("analysts_agent")
        recs = {"strong_buy": 6, "buy": 20, "hold": 13, "sell": 3, "strong_sell": 3,
                "history": [{"strong_buy": 6, "buy": 20, "hold": 13, "sell": 3, "strong_sell": 3},
                            {"strong_buy": 2, "buy": 10, "hold": 20, "sell": 5, "strong_sell": 3}]}
        ups = [{"date": "2026-11-11", "action": "up"}, {"date": "2026-10-01", "action": "down"},
               {"date": "2025-01-01", "action": "up"}]
        out = m.summarize(recs, ups, date(2026, 11, 14))
        self.assertAlmostEqual(out["consensus_score"], 0.51, places=2)  # (12+20-3-6)/45
        self.assertEqual(out["consensus_label"], "compra")
        self.assertGreater(out["trend"], 0)
        self.assertEqual(out["changes_90d"], {"up": 1, "down": 1, "init": 0, "net": 0, "total": 2})

    def test_price_targets(self):
        m = load("price_targets_agent")
        out = m.summarize({"low": 245, "high": 400, "mean": 342.5, "median": 355}, 356.27,
                          [{"date": "2026-11-11", "price_target": 425, "prior_price_target": 400, "firm": "X"}],
                          date(2026, 11, 14))
        self.assertAlmostEqual(out["upside_mean_pct"], -3.87, places=2)
        self.assertEqual(out["raised_90d"], 1)


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.m = load("guard_agent")
        self.dossier = {"price_targets": {"upside_mean_pct": 12.4567, "mean": 400.0},
                        "indicators": {"rsi14": 71.3, "close": 356.27},
                        "profile": {"market_cap_usd": 5.177e12},
                        "news_4h": {"items": [{"summary": "receitas de 94,9 mil milhões de dólares"}]}}

    def test_portuguese_formats_and_units(self):
        texts = ["Potencial de 12,5% até ao alvo médio de 400 USD", "RSI de 71,3 e preço de $356,27",
                 "Capitalização de 5,18 biliões de dólares", "Receitas de 94,9 mil milhões"]
        out = self.m.check_numbers(texts, self.dossier)
        self.assertEqual(out["unverified"], [])
        self.assertGreaterEqual(out["checked"], 5)

    def test_invented_number_is_flagged(self):
        out = self.m.check_numbers(["Margem de 47,8% e alvo de 512 USD"], self.dossier)
        self.assertEqual(out["unverified"], ["47,8", "512"])

    def test_ignores_counts_years_and_windows(self):
        out = self.m.check_numbers(["3 analistas subiram o rating em 2026; acima da SMA de 200 dias e do máximo de 52 semanas"],
                                   self.dossier)
        self.assertEqual(out["checked"], 0)

    def test_synthesis_lowers_confidence_and_lists_gaps(self):
        decision = {"rating": "buy", "confidence": 0.7, "horizon": "6-12 meses",
                    "reasons": ["Margem de 47,8%"], "risks": ["Valorização exigente"]}
        s = self.m.run(decision, {**self.dossier, "sentiment": None},
                       {"symbol": "AAPL", "price": 356.27, "currency": "USD", "market": "US"}, "v2", "run1")
        self.assertAlmostEqual(s.confidence, 0.65)
        self.assertEqual(s.data_gaps, ["sentiment"])
        self.assertEqual(s.version, "v2")
        self.assertTrue(s.warnings)


class AlertDiffTests(unittest.TestCase):
    def test_reasons_diff(self):
        m = load("change_alert_agent")
        d = m.reasons_diff(["Consenso de compra com 26 analistas", "RSI em sobrecompra"],
                           ["Consenso de compra com 27 analistas", "Resultados a 6 dias"])
        self.assertEqual(d["added"], ["Resultados a 6 dias"])
        self.assertEqual(d["removed"], ["RSI em sobrecompra"])


if __name__ == "__main__":
    unittest.main()
