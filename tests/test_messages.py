"""Mensagens do Telegram: formato compacto, números em português, escape de HTML, limites de tamanho."""
import json
import re
import unittest
from pathlib import Path

from core import db, messages as M
from core.changes import Change
from core.ratings import IpoRating, Rating
from core.schemas import IpoSynthesis, Synthesis
from tools import telegram_bot as bot

ROOT = Path(__file__).resolve().parent.parent


def visible(html_text: str) -> str:
    return re.sub(r"<[^>]+>", "", html_text)


class FormatTests(unittest.TestCase):
    def test_numbers_pt(self):
        self.assertEqual(M.price_pt(356.4), "356,40")
        self.assertEqual(M.price_pt(206000.0), "206 000")
        self.assertEqual(M.big_pt(916.09e9), "916 mil M")
        self.assertEqual(M.big_pt(1.0208e12), "1,02 biliões")
        self.assertEqual(M.big_pt(74.0e9), "74,0 mil M")
        self.assertEqual(M.range_pt(916.09e9, 1.0208e12, "USD"), "916 mil M–1,02 biliões USD")
        self.assertEqual(M.price_range_pt("70.00-78.00", "USD"), "70–78 USD")
        self.assertIsNone(M.price_range_pt(None))

    def test_names_dates_exchanges(self):
        self.assertEqual(M.short_name("ANTHROPIC, PBC"), "Anthropic")
        self.assertEqual(M.short_name("Mitsubishi UBE Cement Corporation (MUCC / UBE三菱セメント)"), "Mitsubishi UBE Cement")
        self.assertEqual(M.exchange_short("NASDAQ Global Select"), "Nasdaq")
        self.assertEqual(M.exchange_short("Tokyo Stock Exchange (segmento não divulgado)"), "Tóquio")
        self.assertTrue(M.date_pt("2026-11-19").startswith("19 nov"))
        self.assertIsNone(M.date_pt("data por confirmar"))
        self.assertEqual(M.command_arg("005930.KS"), "005930_KS")

    def test_shorten_and_first_clause(self):
        self.assertLessEqual(len(M.shorten("palavra " * 40, 80)), 80)
        self.assertEqual(M.first_clause("Receita +15,06% YoY. Margem a subir"), "Receita +15,06% YoY")


class RatingMessageTests(unittest.TestCase):
    def test_compact_rating_change(self):
        s = Synthesis(ticker="AAPL", rating="buy", confidence=0.6, price=356.4, currency="USD", version="v2",
                      key_points=["Qualidade muito alta: Piotroski 9/9", "Consenso de compra <forte>"],
                      reasons=["razão longa " * 30])
        msg = M.rating_change(Change("AAPL", Rating.HOLD, Rating.BUY, "confirmed"), s,
                              {"added": ["Resultados acima do esperado"], "removed": []})
        lines = msg.split("\n")
        self.assertTrue(lines[0].startswith("🟢 <b>AAPL — HOLD → COMPRA</b>"))
        self.assertIn("356,40 USD · confiança 60% · confirmada", lines[1])
        self.assertIn("&lt;forte&gt;", msg)  # HTML escapado
        self.assertIn("/detalhe_AAPL", msg)
        self.assertLessEqual(len(visible(msg)), 450)
        self.assertLessEqual(len(lines), 12)

    def test_fallback_without_short_fields(self):
        s = Synthesis(ticker="X", rating="sell", confidence=0.5, reasons=["Primeira oração curta. Resto muito longo " * 5])
        msg = M.rating_change(Change("X", Rating.HOLD, Rating.SELL, "confirmed"), s)
        self.assertIn("• Primeira oração curta", msg)


class IpoMessageTests(unittest.TestCase):
    def test_compact_ipo_with_stored_payload(self):
        s = IpoSynthesis(name="ANTHROPIC, PBC", symbol="ANT", exchange="NASDAQ Global Select",
                         ipo_date="2026-11-19 (pricing esperado a 2026-11-18, segundo a imprensa)", rating="neutro",
                         confidence=0.5, deal={"price_range": "70.00-78.00", "currency": "USD",
                                               "implied_valuation_low": 916.09e9, "implied_valuation_high": 1.0208e12},
                         valuation_view="v", financials="f", ipo_window="w",
                         bull_case=["A receita cresceu 13x em termos homólogos. Mais texto…"],
                         bear_case=["A valorização vai até 1,4 biliões. Mais texto…"], watch_points=["x"],
                         pros_short=["Receita ×13 num ano"], cons_short=["~29× a receita, acima dos peers"])
        self.assertEqual(s.ipo_date, "2026-11-19")  # comentário retirado da data
        msg = M.ipo_rating(s, IpoRating.NEUTRO, None, "/ipo_ANT")
        lines = msg.split("\n")
        self.assertEqual(lines[0], "🟡 <b>IPO Anthropic (ANT) — NEUTRO</b>")
        self.assertIn("Nasdaq · 19 nov", lines[1])
        self.assertIn("Preço 70–78 USD · valor 916 mil M–1,02 biliões USD", lines[2])
        self.assertIn("👍 Receita ×13 num ano", msg)
        self.assertLessEqual(len(visible(msg)), 450)

    def test_new_ipos_and_lockup(self):
        msg = M.new_ipos([{"date": "2026-11-19", "name": "ANTHROPIC, PBC", "symbol": "ANT", "exchange": "NASDAQ Global Select",
                           "price_range": "70.00-78.00", "currency": "USD", "value_usd": 74.0e9},
                          {"date": None, "name": "Mitsubishi UBE Cement Corporation", "exchange": "Tokyo Stock Exchange"}])
        self.assertIn("• 19 nov", msg)
        self.assertIn("Anthropic (ANT) · Nasdaq · 70–78 USD · 74,0 mil M USD", msg)
        self.assertIn("data por confirmar · Mitsubishi UBE Cement · Tóquio · dimensão por divulgar", msg)
        lk = M.lockup("XYZ", "XYZ CORP", "2026-11-20", 6, False, {"float_pct": 22.0, "days_to_trade_locked": 8.5})
        self.assertIn("fim do lock-up em 6 dia(s)", lk)
        self.assertIn("não confirmado", lk)


class BotDetailTests(unittest.TestCase):
    def test_ticker_resolution(self):
        conn = db.connect(":memory:")
        db.save_run(conn, ticker="005930.KS", rating=0, confidence=0.4, price=206000.0, reasons=["R1"], payload={})
        self.assertEqual(bot.resolve_ticker(conn, "005930_KS"), "005930.KS")
        self.assertIsNone(bot.resolve_ticker(conn, "NADA"))


if __name__ == "__main__":
    unittest.main()
