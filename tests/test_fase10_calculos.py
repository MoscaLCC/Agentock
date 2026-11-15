"""Fase 10 — fórmulas verificadas contra referências independentes (cada teste falhava antes da correção).

As referências estão no docs/AUDITORIA.md: valores recalculados à mão / em numpy, ou publicados pelo fornecedor.
"""
import importlib.util
import math
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from core import sessions
from core.util import major_currency

ROOT = Path(__file__).resolve().parent.parent


def load(agent: str):
    spec = importlib.util.spec_from_file_location(f"_t10_{agent}", ROOT / "agents" / agent / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fin(**ratios) -> dict:
    """Contas mínimas: FCF 100, dívida líquida 0 (caixa = dívida), 10 ações."""
    return {"fiscal_years": [2025, 2024], "currency": "GBP",
            "income": {"revenue": [1000.0, 900.0], "net_income": [100.0, 90.0], "gross_profit": [400.0, 350.0],
                       "operating_income": [150.0, 130.0], "ebit": [150.0, 130.0], "ebitda": [200.0, 180.0],
                       "interest_expense": [10.0, 10.0]},
            "balance": {"total_debt": [50.0, 50.0], "cash": [50.0, 50.0], "shares": [10.0, 10.0],
                        "current_assets": [300.0, 280.0], "current_liabilities": [150.0, 150.0]},
            "cashflow": {"free_cash_flow": [100.0, 90.0]},
            "ratios": {"beta": 1.0, **ratios}, "shares": {"outstanding": 10.0}}


class MinorCurrencyTests(unittest.TestCase):
    """A5 — Londres cota em pence (GBp) e as contas vêm em libras: sem normalizar, DCF e Altman erravam 100×."""

    def test_major_currency(self):
        self.assertEqual(major_currency("GBp"), ("GBP", 100.0))
        self.assertEqual(major_currency("GBX"), ("GBP", 100.0))
        self.assertEqual(major_currency("ZAc"), ("ZAR", 100.0))
        self.assertEqual(major_currency("ILA"), ("ILS", 100.0))
        self.assertEqual(major_currency("USD"), ("USD", 1.0))
        self.assertEqual(major_currency("KRW"), ("KRW", 1.0))
        self.assertEqual(major_currency(None), (None, 1.0))

    def test_dcf_per_share_is_in_quote_units(self):
        fd = load("fundamental_data_agent")
        in_pounds = fd.analyse(fin(), 12.0)["dcf"]
        in_pence = fd.analyse(fin(), 1200.0, minor_div=100.0)["dcf"]          # mesma ação, cotada em pence
        self.assertAlmostEqual(in_pence["value_per_share"], in_pounds["value_per_share"] * 100, delta=1.0)
        self.assertAlmostEqual(in_pence["upside_pct"], in_pounds["upside_pct"], places=1)

    def test_fcf_yield_uses_major_units(self):
        fd = load("fundamental_data_agent")
        out = fd.analyse(fin(market_cap=2000.0), 1200.0, minor_div=100.0)       # market cap do Yahoo em libras
        self.assertEqual(out["valuation"]["fcf_yield_pct"], 5.0)                # 100 / 2000


class ShareClassTests(unittest.TestCase):
    """B7 — `sharesOutstanding` é só uma classe (GOOGL: 5,888 mil M classe A vs 12,29 mil M no total)."""

    def test_divisor_is_market_cap_over_price(self):
        fd = load("fundamental_data_agent")
        self.assertAlmostEqual(fd.share_count(5.888e9, 3.636e12, 295.77) / 1e9, 12.29, places=2)

    def test_falls_back_to_outstanding(self):
        fd = load("fundamental_data_agent")
        self.assertEqual(fd.share_count(10.0, None, 12.0), 10.0)
        self.assertEqual(fd.share_count(10.0, 120.0, None), 10.0)
        self.assertEqual(fd.share_count(10.0, 5e9, 12.0), 10.0)                 # market cap incoerente (×10^7): ignora

    def test_dcf_uses_all_share_classes(self):
        fd = load("fundamental_data_agent")
        one_class = fd.analyse(fin(), 12.0)["dcf"]["value_per_share"]
        two_classes = fd.analyse(fin(market_cap=240.0), 12.0)["dcf"]["value_per_share"]   # 240 / 12 = 20 ações
        self.assertAlmostEqual(two_classes, one_class / 2, delta=0.02)


class NegativeMultipleTests(unittest.TestCase):
    """C2 — CPNG: EV/EBITDA −68,12 dava "desconto" de −686% face aos peers."""

    def test_negative_multiple_is_not_compared(self):
        fd = load("fundamental_data_agent")
        out = fd.analyse(fin(ev_to_ebitda=-68.12, trailing_pe=20.0), 12.0,
                         comps={"medians": {"ev_to_ebitda": 11.62, "trailing_pe": 25.0, "forward_pe": -3.0}})
        self.assertIsNone(out["vs_peers"]["ev_to_ebitda"])
        self.assertEqual(out["vs_peers"]["trailing_pe"], -20.0)
        self.assertIsNone(out["vs_peers"]["forward_pe"])

    def test_medians_ignore_negative_multiples(self):
        comps = load("comps_agent")
        rows = [{"ev_to_ebitda": -68.0, "price_to_book": 2.0, "roe": -5.0},
                {"ev_to_ebitda": 10.0, "price_to_book": -1.0, "roe": 15.0},
                {"ev_to_ebitda": 14.0, "price_to_book": 4.0, "roe": 25.0}]
        med = comps.medians(rows)
        self.assertEqual(med["ev_to_ebitda"], 12.0)
        self.assertEqual(med["price_to_book"], 3.0)
        self.assertEqual(med["roe"], 15.0)                                      # rentabilidades negativas contam


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.hm = load("health_momentum_agent")

    def test_debt_to_equity_from_yahoo_is_always_percent(self):
        """B8 — Samsung: 2,799 significa 2,8% (não 2,8×). Piotroski 6/9 + zona segura → 83 (dava 66)."""
        out = self.hm.scores({"ratios": {"debt_to_equity": 2.799}}, {"score_9": 6.0}, {"zone": "segura"}, {})
        self.assertEqual(out["health_score"], 83)

    def test_debt_to_equity_prefers_the_balance_sheet(self):
        f = {"ratios": {"debt_to_equity": 2.799}, "balance": {"total_debt": [300.0], "equity": [100.0]}}
        out = self.hm.scores(f, {"score_9": 6.0}, {"zone": "segura"}, {})       # 3× capital → pior banda (15)
        self.assertEqual(out["health_score"], 66)

    def test_no_dilution_uses_net_issuance_not_noisy_share_counts(self):
        """C6 — Samsung: a contagem do Yahoo incluía preferenciais num ano e não no outro; houve recompras."""
        f = {"income": {"net_income": [1, 1], "revenue": [1, 1], "gross_profit": [1, 1]},
             "balance": {"total_assets": [1, 1], "shares": [6.630e9, 5.940e9]},
             "cashflow": {"operating_cash_flow": [1, 1], "buybacks": [-8.0e12, 0.0], "stock_issuance": [None, None]}}
        self.assertTrue(self.hm.piotroski(f)["tests"]["sem_diluicao"])
        f["cashflow"] = {"operating_cash_flow": [1, 1], "buybacks": [0.0, 0.0], "stock_issuance": [5.0e12, 0.0]}
        self.assertFalse(self.hm.piotroski(f)["tests"]["sem_diluicao"])
        f["cashflow"] = {"operating_cash_flow": [1, 1]}                         # sem dados de caixa: n.º de ações
        self.assertFalse(self.hm.piotroski(f)["tests"]["sem_diluicao"])

    def test_altman_reference(self):
        """Altman (1968): Z = 1,2·WC/TA + 1,4·RE/TA + 3,3·EBIT/TA + 0,6·MVE/TL + 1,0·Vendas/TA."""
        f = {"income": {"ebit": [150.0], "revenue": [1000.0]},
             "balance": {"total_assets": [2000.0], "total_liabilities": [800.0], "working_capital": [300.0],
                         "retained_earnings": [600.0]}}
        z = 1.2 * 300 / 2000 + 1.4 * 600 / 2000 + 3.3 * 150 / 2000 + 0.6 * 1600 / 800 + 1000 / 2000
        self.assertAlmostEqual(self.hm.altman(f, 1600.0, "Technology")["z"], round(z, 2))
        self.assertEqual(self.hm.altman(f, 1600.0, "Technology")["zone"], "cinzenta")   # 2,55


class CrossListingTests(unittest.TestCase):
    """B9 — a pesquisa por nome devolvia outras empresas (Samsung → NU, Coupang → AMD) como "cotações cruzadas"."""

    def test_only_the_same_company_counts(self):
        prof = load("profile_agent")
        self.assertFalse(prof.same_company("Nu Holdings Ltd.", "Samsung Electronics Co., Ltd."))
        self.assertFalse(prof.same_company("Advanced Micro Devices, Inc.", "Coupang, Inc."))
        self.assertTrue(prof.same_company("Alibaba Group Holding Limited", "Alibaba Group Holding Ltd"))
        self.assertTrue(prof.same_company("Samsung Electronics Co Ltd GDR", "Samsung Electronics Co., Ltd."))
        self.assertTrue(prof.same_company("SAMSUNG ELECTRONICS", "Samsung Electronics Co., Ltd."))
        self.assertFalse(prof.same_company(None, "Apple Inc."))
        self.assertFalse(prof.same_company("Apple Hospitality REIT", "Apple Inc."))


class MarketShareCacheTests(unittest.TestCase):
    """A3 — a cache por indústria servia à Coupang a análise da SSU e à Samsung a da Apple."""

    def test_market_share_is_cached_per_company(self):
        from core.spec import read_config
        self.assertEqual(read_config("market_share_agent")["cache_key"], ["profile.symbol"])


class SessionBreakTests(unittest.TestCase):
    """C3 — a pausa de almoço (Hong Kong, Tóquio) era tratada como mercado fechado desde a véspera."""

    def test_lunch_break_is_an_open_session(self):
        at = datetime(2026, 11, 13, 4, 30, tzinfo=timezone.utc)                 # 12:30 em Hong Kong
        self.assertTrue(sessions.market_state("XHKG", at)["open"])
        self.assertTrue(sessions.market_state("XTKS", datetime(2026, 11, 13, 3, 0, tzinfo=timezone.utc))["open"])

    def test_closed_after_the_close_and_dst(self):
        st = sessions.market_state("XHKG", datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc))
        self.assertEqual((st["open"], st["last_close"]), (False, "2026-11-13T08:00:00+00:00"))
        self.assertTrue(sessions.market_state("XNYS", datetime(2026, 7, 15, 13, 45, tzinfo=timezone.utc))["open"])
        self.assertFalse(sessions.market_state("XNYS", datetime(2026, 12, 15, 13, 45, tzinfo=timezone.utc))["open"])


class TechnicalReferenceTests(unittest.TestCase):
    """Indicadores contra implementações independentes escritas aqui (definições originais)."""

    @classmethod
    def setUpClass(cls):
        cls.ti = load("technical_indicators_agent")
        x = 100.0
        closes = []
        for i in range(260):                                                    # série determinística com ruído
            x *= 1 + 0.012 * math.sin(i * 0.37) + 0.004 * math.cos(i * 1.3) + 0.0008
            closes.append(round(x, 4))
        cls.closes = closes
        cls.bars = [{"t": f"2026-01-01T00:00:00Z", "o": c, "h": c * 1.01, "l": c * 0.99, "c": c, "v": 1000 + i}
                    for i, c in enumerate(closes)]
        days = pd.bdate_range("2025-11-03", periods=260)
        for b, d in zip(cls.bars, days):
            b["t"] = d.strftime("%Y-%m-%dT00:00:00Z")
        cls.out = cls.ti.compute(cls.bars)

    def test_rsi_wilder(self):
        c = self.closes
        gains = [max(b - a, 0) for a, b in zip(c, c[1:])]
        losses = [max(a - b, 0) for a, b in zip(c, c[1:])]
        ag, al = sum(gains[:14]) / 14, sum(losses[:14]) / 14
        for g, l in zip(gains[14:], losses[14:]):                               # suavização de Wilder
            ag, al = (ag * 13 + g) / 14, (al * 13 + l) / 14
        self.assertAlmostEqual(self.out["rsi14"], round(100 - 100 / (1 + ag / al), 2), delta=0.05)

    def test_sma_and_bollinger_population_std(self):
        """D1 — Bollinger usa o desvio-padrão populacional (ddof=0); com o amostral as bandas ficavam 2,6% mais largas."""
        last20 = self.closes[-20:]
        mid = sum(last20) / 20
        sd = math.sqrt(sum((v - mid) ** 2 for v in last20) / 20)
        self.assertAlmostEqual(self.out["sma20"], round(mid, 2), delta=0.01)
        self.assertAlmostEqual(self.out["bollinger"]["upper"], round(mid + 2 * sd, 2), delta=0.01)
        self.assertAlmostEqual(self.out["bollinger"]["lower"], round(mid - 2 * sd, 2), delta=0.01)

    def test_macd(self):
        def ema(xs, n):
            k, e = 2 / (n + 1), sum(xs[:n]) / n
            for v in xs[n:]:
                e = v * k + e * (1 - k)
            return e
        c = self.closes
        macd_series = []
        for end in range(26, len(c) + 1):
            macd_series.append(ema(c[:end], 12) - ema(c[:end], 26))
        self.assertAlmostEqual(self.out["macd"]["macd"], macd_series[-1], delta=0.02)
        self.assertAlmostEqual(self.out["macd"]["signal"], ema(macd_series, 9), delta=0.02)

    def test_annualised_volatility(self):
        rets = [math.log(b / a) for a, b in zip(self.closes, self.closes[1:])][-252:]
        mu = sum(rets) / len(rets)
        sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / (len(rets) - 1))
        self.assertAlmostEqual(self.out["volatility_ann_pct"], round(sd * math.sqrt(252) * 100, 2), delta=0.05)


class ForecastStatsTests(unittest.TestCase):
    """C7 — a mediana do intervalo passa a ser o preço atual (era o preço − ½σ²: −25,7% a 12 meses na Samsung)."""

    def setUp(self):
        self.fs = load("forecast_stats_agent")
        rng, x, self.closes = 12345, 100.0, []
        for _ in range(300):
            rng = (1103515245 * rng + 12345) % 2 ** 31
            x *= math.exp((rng / 2 ** 31 - 0.5) * 0.09)
            self.closes.append(x)

    def test_median_is_the_current_price(self):
        out = self.fs.ranges(200.0, self.closes)
        for h in ("1m", "3m", "12m"):
            self.assertEqual(out["horizons"][h]["p50"], 200.0)
            self.assertLess(out["horizons"][h]["p10"], 200.0)
            self.assertGreater(out["horizons"][h]["p90"], 200.0)

    def test_quantiles_follow_the_lognormal_formula(self):
        out = self.fs.ranges(200.0, self.closes)
        s = out["daily_vol_pct"] / 100 * math.sqrt(252)
        self.assertAlmostEqual(out["horizons"]["12m"]["p90"], 200 * math.exp(1.2816 * s), delta=0.5)
        self.assertAlmostEqual(out["horizons"]["12m"]["p10"], 200 * math.exp(-1.2816 * s), delta=0.5)

    def test_penny_stock_keeps_significant_digits(self):
        out = self.fs.ranges(0.093, [c / 1000 for c in self.closes])
        self.assertGreater(out["horizons"]["1m"]["p10"], 0)
        self.assertNotEqual(out["horizons"]["1m"]["p10"], out["horizons"]["1m"]["p90"])


if __name__ == "__main__":
    unittest.main()
