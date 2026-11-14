"""Testes das Fases 7-9 (sem rede)."""
import importlib.util
import unittest
from datetime import date
from pathlib import Path

import yaml

from core import db
from tools import evaluation, history_page

ROOT = Path(__file__).resolve().parent.parent


def load(rel: str):
    spec = importlib.util.spec_from_file_location(f"_t79_{rel.replace('/', '_')}", ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def bars(start: date, prices: list[float]):
    from datetime import timedelta
    return [{"t": (start + timedelta(days=i)).isoformat(), "c": p} for i, p in enumerate(prices)]


class EvaluationTests(unittest.TestCase):
    def test_returns_and_hit(self):
        b = bars(date(2026, 1, 1), [100 + i for i in range(40)])
        out = evaluation.returns_for(b, date(2026, 1, 1), 100.0, date(2026, 3, 1))
        self.assertEqual((out["1d"], out["7d"], out["30d"]), (1.0, 7.0, 30.0))
        self.assertIsNone(evaluation.returns_for(b, date(2026, 1, 1), 100.0, date(2026, 1, 20))["30d"])  # ainda não
        self.assertTrue(evaluation.hit(1, 2.0) and evaluation.hit(-2, -1.0) and evaluation.hit(0, 2.5))
        self.assertFalse(evaluation.hit(0, 4.0) or evaluation.hit(2, -0.1))

    def test_report(self):
        conn = db.connect(":memory:")
        for rating, ret, bench, ver in ((2, 10, 2, "v2"), (1, -3, 1, "v2"), (0, 1, 0, "v1"), (-1, -5, 1, "v1")):
            rid = db.save_run(conn, ticker="X", rating=rating, confidence=0.6, price=10, reasons=[], payload={},
                              version=ver, market="US")
            conn.execute("UPDATE runs SET ret_30d=?, bench_30d=? WHERE id=?", (ret, bench, rid))
        rep = evaluation.build_report(conn)
        self.assertEqual(rep["evaluated_30d"], 4)
        self.assertFalse(rep["enough_data"])
        self.assertEqual(rep["overall"]["hit_rate"], 0.75)
        self.assertEqual(rep["by_version"]["v2"]["hit_rate"], 0.5)
        self.assertIn("Por versão", evaluation.report_text(rep))


class UniverseTests(unittest.TestCase):
    def setUp(self):
        self.m = load("agents/universe_agent/run.py")
        self.cfg = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text(encoding="utf-8"))

    def test_yaml_norway_is_a_string(self):
        self.assertIn("no", self.cfg["regions"])  # sem aspas seria False

    def test_select_prefers_most_liquid_listing(self):
        q = lambda s, name, ex, cur, fin, mc, tv: {"symbol": s, "name": name, "exchange": ex, "currency": cur,  # noqa: E731
                                                  "financial_currency": fin, "market_cap_usd": mc,
                                                  "traded_value_usd": tv, "quote_type": "EQUITY"}
        quotes = [q("AAPL", "Apple Inc.", "NMS", "USD", "USD", 5.1e12, 9e9),
                  q("APC.DE", "Apple Inc.", "GER", "EUR", "USD", 5.5e12, 5e7),
                  q("ASML.AS", "ASML Holding N.V.", "AMS", "EUR", "EUR", 5.6e11, 9e8),
                  q("ASME.DE", "ASML Holding NV", "GER", "EUR", "EUR", 5.7e11, 1e7),
                  q("T2TD34.SA", "The Trade Desk, Inc.", "SAO", "BRL", "USD", 7.4e11, 1e6)]
        out = self.m.select(quotes, self.cfg, 10)
        self.assertEqual([x["symbol"] for x in out], ["AAPL", "ASML.AS"])  # BDR excluído

    def test_validate_alternatives(self):
        self.assertEqual(self.m.validate([{"symbol": "GOOG"}, {"symbol": "TSM"}], ["GOOGL|GOOG", "2330.TW|TSM", "AAPL"]),
                         ["AAPL"])


class HistoryPageTests(unittest.TestCase):
    def test_svg_chart(self):
        svg = history_page.svg_chart([("2026-11-01", 100.0), ("2026-11-02", 105.0)], [("2026-11-02", 105.0, 2)])
        self.assertIn("<circle", svg)
        self.assertIn("Compra forte", svg)


if __name__ == "__main__":
    unittest.main()
