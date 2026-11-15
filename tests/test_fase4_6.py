"""Testes dos scripts das Fases 4-6b (sem rede)."""
import importlib.util
import math
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(rel: str):
    spec = importlib.util.spec_from_file_location(f"_t46_{rel.replace('/', '_')}", ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class NewsScriptsTests(unittest.TestCase):
    def test_dedupe(self):
        from core import news as m
        items = [{"title": "Samsung in talks to buy Modine", "url": "https://x.com/a"},
                 {"title": "Samsung in talks to buy Modine - report", "url": "https://y.com/b"},
                 {"title": "Samsung HBM4E mass production", "url": "https://z.com/c"}]
        self.assertEqual(m.groups(items), [[0, 1], [2]])


class CompsTests(unittest.TestCase):
    def test_medians_ignore_negative_pe(self):
        m = load("agents/comps_agent/run.py")
        rows = [{"trailing_pe": 20, "roe": 10}, {"trailing_pe": -5, "roe": 30}, {"trailing_pe": 30, "roe": 20}]
        med = m.medians(rows)
        self.assertEqual(med["trailing_pe"], 25)
        self.assertEqual(med["roe"], 20)
        rel = m.relative({"trailing_pe": 28, "roe": 15}, med)
        self.assertEqual((rel["trailing_pe"], rel["roe"]), (3, -5))


class ForecastTests(unittest.TestCase):
    def test_ranges(self):
        m = load("agents/forecast_stats_agent/run.py")
        closes = [100 * math.exp(0.01 * math.sin(i)) for i in range(300)]
        out = m.ranges(100.0, closes)
        h = out["horizons"]["12m"]
        self.assertLess(h["p10"], h["p50"])
        self.assertEqual(h["p50"], 100.0)  # Fase 10 (D27): a mediana é o preço atual, sem tendência
        self.assertLess(h["p90"] - h["p10"], 100)
        self.assertFalse(m.ranges(100.0, closes[:10])["available"])

    def test_forecast_validator_normalizes(self):
        sch = load("agents/forecast_agent/schema.py")
        f = sch.Forecast(scenarios=[
            {"name": "bull", "probability": 0.3, "price_1m": 90, "price_3m": 120, "price_12m": 150, "drivers": ["x"]},
            {"name": "bear", "probability": 0.3, "price_1m": 95, "price_3m": 80, "price_12m": 70, "drivers": ["y"]},
            {"name": "base", "probability": 0.6, "price_1m": 100, "price_3m": 100, "price_12m": 110, "drivers": ["z"]}],
            summary="s")
        self.assertEqual([s.name for s in f.scenarios], ["bear", "base", "bull"])
        self.assertAlmostEqual(sum(s.probability for s in f.scenarios), 1.0, places=2)
        self.assertEqual([s.price_1m for s in f.scenarios], [90, 95, 100])  # ordenado
        self.assertAlmostEqual(f.expected_12m, 0.25 * 70 + 0.5 * 110 + 0.25 * 150, places=3)


class IpoTests(unittest.TestCase):
    def test_deal_math(self):
        m = load("agents/pre_ipo_agent/scripts/deal_math.py")
        out = m.compute(70, 78, 825e6, 9.5e9, primary=600e6, greenshoe_pct=15, revenue=5e9)
        self.assertEqual(out["implied_valuation_low"], 665e9)
        self.assertEqual(out["free_float_pct"], 9.99)
        self.assertEqual(out["implied_ev_sales_high"], 148.2)

    def test_ipo_memory_message_and_change(self):
        from core import db
        from core.schemas import IpoSynthesis
        m = load("agents/ipo_memory_agent/run.py")

        class Cap:
            sent = []

            def send(self, t, html=False):
                self.sent.append(t)
                return True

        s = IpoSynthesis(name="X Corp", rating="neutro", confidence=0.5, deal={"price_range": "10-12"},
                         valuation_view="v", financials="f", ipo_window="w", bull_case=["a"], bear_case=["b"],
                         watch_points=["c"], not_disclosed=["lock-up"])
        conn = db.connect(":memory:")
        cap = Cap()
        m.default_notifier = lambda: cap
        self.assertEqual(m.run(s, conn=conn)["previous"], None)
        self.assertIsNone(m.run(s, conn=conn)["sent"])  # igual à anterior: não repete
        s2 = s.model_copy(update={"rating": "subscrever"})
        out = m.run(s2, conn=conn)
        self.assertEqual((out["rating"], out["previous"]), ("Subscrever", "Neutro"))
        self.assertIn("(antes: Neutro)", cap.sent[-1])
        self.assertEqual(len(cap.sent), 2)


if __name__ == "__main__":
    unittest.main()
