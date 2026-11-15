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
        conn.execute("UPDATE runs SET ts = '2026-01-0' || id || 'T10:00:00+00:00'")   # um dia por classificação
        rep = evaluation.build_report(conn)
        self.assertEqual(rep["evaluated_30d"], 4)
        self.assertFalse(rep["enough_data"])
        self.assertEqual(rep["overall"]["hit_rate"], 0.75)
        self.assertEqual(rep["by_version"]["v2"]["hit_rate"], 0.5)
        self.assertIn("Por versão", evaluation.report_text(rep))


class EvaluationRulesTests(unittest.TestCase):
    """B16 — regras de medição da avaliação (Fase 10)."""

    def run_row(self, conn, ticker, rating, ret, bench, ts, version="v2", conf=0.6):
        rid = db.save_run(conn, ticker=ticker, rating=rating, confidence=conf, price=10, reasons=[], payload={},
                          version=version, market="US")
        conn.execute("UPDATE runs SET ret_30d=?, bench_30d=?, ts=? WHERE id=?", (ret, bench, ts, rid))

    def test_base_is_the_close_of_the_analysis_day_not_the_recorded_price(self):
        b = bars(date(2026, 1, 1), [100 + i for i in range(40)])
        # preço gravado antes de um split 10:1 (1000) — as barras já vêm ajustadas (100): o retorno não pode ser −90%
        out = evaluation.returns_for(b, date(2026, 1, 1), 1000.0, date(2026, 3, 1))
        self.assertEqual(out["30d"], 30.0)
        weekend = [x for x in b if x["t"] not in ("2026-01-03", "2026-01-04")]
        out = evaluation.returns_for(weekend, date(2026, 1, 3), None, date(2026, 3, 1))     # análise ao sábado
        self.assertEqual(out["1d"], round((105 / 104 - 1) * 100, 3))                        # base: fecho de 2.ª-feira

    def test_missing_benchmark_is_excluded_not_treated_as_zero(self):
        conn = db.connect(":memory:")
        self.run_row(conn, "A", 1, 10.0, None, "2026-01-05T10:00:00+00:00")
        self.run_row(conn, "B", 1, 5.0, 8.0, "2026-01-05T10:00:00+00:00")
        rep = evaluation.build_report(conn)
        self.assertEqual((rep["evaluated_30d"], rep["excluded"]["sem_indice"]), (1, 1))
        self.assertEqual(rep["overall"]["hit_rate"], 0.0)          # +5% com o índice a +8%: a compra falhou

    def test_same_day_repeats_count_once(self):
        conn = db.connect(":memory:")
        for i in range(5):                                          # AAPL analisada 5 vezes no mesmo dia
            self.run_row(conn, "AAPL", 0 if i < 4 else 1, 4.0, 1.0, f"2026-01-05T1{i}:00:00+00:00")
        self.run_row(conn, "AAPL", 1, 4.0, 1.0, "2026-01-05T09:00:00+00:00", version="v1")
        rep = evaluation.build_report(conn)
        self.assertEqual((rep["evaluated_30d"], rep["excluded"]["repetidas_no_dia"]), (2, 4))
        self.assertEqual(rep["by_version"]["v2"]["n"], 1)
        self.assertEqual(rep["by_rating"]["Compra"]["n"], 2)        # ficou a última do dia (compra), não as 4 "manter"

    def test_directional_calibration_and_small_groups(self):
        conn = db.connect(":memory:")
        for i in range(12):
            self.run_row(conn, f"T{i}", 1, 5.0 if i < 9 else -5.0, 0.0, "2026-01-05T10:00:00+00:00", conf=0.8)
        self.run_row(conn, "H", 0, 1.0, 0.0, "2026-01-05T10:00:00+00:00", conf=0.4)
        rep = evaluation.build_report(conn)
        self.assertEqual((rep["directional"]["n"], rep["directional"]["hit_rate"]), (12, 0.75))
        hi = rep["by_confidence"]["≥0,7"]
        self.assertEqual((hi["avg_confidence"], hi["hit_rate"], hi["enough"]), (0.8, 0.75, True))
        self.assertFalse(rep["by_confidence"]["<0,5"]["enough"])
        text = evaluation.report_text(rep)
        self.assertIn("(N insuficiente)", text)
        self.assertIn("só compras e vendas", text)
        self.assertIn("Fora das estatísticas: 0 sem retorno do índice", text)


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
