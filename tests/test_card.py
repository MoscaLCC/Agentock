"""Cartão visual e secções do Telegram (sem rede)."""
import json
import unittest
from datetime import date, timedelta

from core import charts, db, report_data, sections


def fake_outputs(price=206000.0):
    return {
        "profile": {"name": "Samsung Electronics Co., Ltd.", "currency": "KRW", "change_pct": -0.96},
        "indicators": {"levels": {"supports": [204000.0, 189200.0], "resistances": [249000.0]},
                       "volatility_ann_pct": 77.1},
        "price_targets": {"low": 290000.0, "high": 700000.0, "mean": 475629.0, "upside_mean_pct": 130.9},
        "forecast": {"scenarios": [
            {"name": "bear", "probability": 0.2, "price_1m": 180000, "price_3m": 160000, "price_12m": 105000, "drivers": []},
            {"name": "base", "probability": 0.5, "price_1m": 210000, "price_3m": 212000, "price_12m": 215000, "drivers": []},
            {"name": "bull", "probability": 0.3, "price_1m": 240000, "price_3m": 280000, "price_12m": 340000, "drivers": []}],
            "expected_12m": 230500.0, "summary": "Resumo dos cenários."},
        "technical": {"score": 0}, "fundamental": {"score": 1}, "sentiment": {"score": 1}, "timing": {"score": -1},
        "analysts": {"consensus_score": 1.33, "consensus_label": "compra", "n_analysts": 36},
        "health": {"health_score": 65, "momentum_score": 72},
        "fundamental_data": {"valuation": {"forward_pe": 2.66, "ev_to_ebitda": 3.56, "dividend_yield_pct": 8.93},
                             "balance": {"roe_pct": 41.6}},
        "calendar": {"next_earnings": "2027-01-27"},
        "comps": {"target": {"symbol": "005930.KS", "forward_pe": 2.7, "ev_to_ebitda": 3.6, "operating_margin": 13.1,
                             "ret_12m_pct": 60.1},
                  "peers": [{"symbol": "000660.KS", "forward_pe": 5.0, "ev_to_ebitda": 4.2, "operating_margin": 40.0,
                             "ret_12m_pct": 120.0}],
                  "medians": {"forward_pe": 15.6, "ev_to_ebitda": 9.9, "operating_margin": 20.0, "ret_12m_pct": 10.0}},
        "insiders": {"available": True, "source": "dart", "score": 1, "label": "positivo", "currency": "KRW",
                     "signals": ["Gestão de topo comprou: Presidente executivo (노태문), 630 M KRW em 90 dias"],
                     "windows": {"30": {"buys": 1, "buy_value": 6.3e8, "sells": 0, "sell_value": 0, "net_value": 6.3e8}},
                     "notable": [{"date": "2026-11-12", "name": "이재용", "role": "Chairman", "kind": "doação recebida",
                                  "value": 2.3e12, "planned": False, "note": "doador: 홍라희"}],
                     "routine_180d": {"atribuições": 72, "doações": 1}},
        "news_24h": {"items": [{"title": "Samsung em conversações para comprar a Modine", "url": "https://x.com/a",
                                "source": "Bloomberg", "published_at": "2026-11-13T08:18:00Z", "relevance": 5,
                                "tone": "positivo"}]},
    }


def setup_run(conn, run_id="r1"):
    rid = db.save_run(conn, ticker="005930.KS", rating=1, confidence=0.55, price=206000.0,
                      reasons=["Fundamentais: P/E de 2,7", "Analistas: 36 de 36 recomendam compra"],
                      payload={"headline": "Lucros fortes e preço baixo", "key_points": ["P/E de 2,7", "36 analistas"],
                               "risks": ["Ciclo da memória: margens voláteis"],
                               "debate": {"bull": "Barata.", "bear": "Pico de ciclo."}},
                      version="v2", market="KR", currency="KRW", run_id=run_id)
    for node, out in fake_outputs().items():
        db.save_agent_output(conn, run_id=run_id, node=node, agent=node, ticker=None, status="ok", cached=False,
                             output=json.dumps(out), error=None, cost_usd=None, duration_ms=1, turns=None)
    return rid


def bars(n=300, start=250000.0):
    d0 = date.today() - timedelta(days=n)
    return [{"t": (d0 + timedelta(days=i)).isoformat(), "c": start - i * 100, "v": 1e6} for i in range(n)]


class CardTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.rid = setup_run(self.conn)
        self.data = report_data.latest(self.conn, "005930.KS")

    def test_report_data_gathers_outputs(self):
        self.assertEqual(self.data["run"]["id"], self.rid)
        self.assertIn("forecast", self.data["outputs"])

    def test_card_renders_png(self):
        png = charts.stock_card(self.data, bars())
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertGreater(len(png), 20000)

    def test_card_renders_with_missing_data(self):
        empty = {**self.data, "outputs": {}}
        self.assertTrue(charts.stock_card(empty, []).startswith(b"\x89PNG"))

    def test_labels_do_not_overlap(self):
        items = [(206000, "preço · 206 000"), (215000, "base 50% · 215 000"), (220000, "x · 1")]
        levels = charts.place_labels(items, 100000, 700000, [1.0, 1.75, -1.15, -1.85])
        self.assertEqual(len(set(levels)), 3)  # três etiquetas próximas → três níveis diferentes


class SectionTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.rid = setup_run(self.conn)
        self.data = report_data.latest(self.conn, "005930.KS")

    def test_buttons_fit_telegram_limits(self):
        kb = sections.buttons(self.rid)
        datas = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]
        self.assertEqual(len(datas), 7)
        self.assertTrue(all(len(d.encode()) <= 64 for d in datas))

    def test_caption_is_short(self):
        cap = sections.caption(self.data, "SSU → Samsung Electronics (005930.KS); SSU: sem negociação")
        self.assertIn("Pedido: SSU → Samsung", cap)
        self.assertLess(len(cap), 1024)

    def test_tables_fit_phone_width(self):
        for txt in (sections.sec_peers(self.data), sections.sec_scenarios(self.data), sections.sec_insiders(self.data)):
            pre = txt.split("<pre>")[1].split("</pre>")[0]
            self.assertTrue(all(len(line) <= 37 for line in pre.split("\n")), pre)

    def test_scenarios_are_relative_to_price(self):
        txt = sections.sec_scenarios(self.data)
        self.assertIn("pessimista", txt)
        self.assertIn("-49%", txt)  # 105 000 face a 206 000

    def test_dispatch_all_sections(self):
        for key in sections.BUILDERS:
            out = sections.section(self.conn, f"s|{self.rid}|{key}")
            self.assertTrue(out.startswith("<b>"), key)
        self.assertIn("Bloomberg", sections.section(self.conn, f"s|{self.rid}|nw"))


class DividendTests(unittest.TestCase):
    def test_trailing_yield_uses_paid_dividends(self):
        import pandas as pd
        from core.data.providers.yfinance_p import trailing_yield
        idx = pd.to_datetime(["2025-06-30", "2026-03-31", "2026-06-30", "2026-09-30"]).tz_localize("Asia/Seoul")
        divs = pd.Series([1000.0, 1500.0, 1500.0, 3283.0], index=idx)
        now = pd.Timestamp("2026-11-14", tz="Asia/Seoul")
        self.assertEqual(trailing_yield(divs, 206000.0, now), 3.05)  # 6 283 / 206 000 (o de 2025 já não conta)
        self.assertIsNone(trailing_yield(pd.Series(dtype=float), 206000.0, now))


if __name__ == "__main__":
    unittest.main()
