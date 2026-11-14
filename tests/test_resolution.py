"""Resolução de pedidos no profile_agent (caso real: 'SSU' = Samsung em Frankfurt ≠ SIGNA deslistada)."""
import importlib.util
import unittest
from datetime import date, timedelta
from pathlib import Path

from core.data.router import DataUnavailable
from tools import telegram_bot as bot

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("_t_profile", ROOT / "agents" / "profile_agent" / "run.py")
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)


class Res:
    def __init__(self, data, provider="fake"):
        self.data, self.provider = data, provider


def bars(price: float, volume: float, n: int = 20):
    return [{"t": (date.today() - timedelta(days=n - i)).isoformat(), "c": price, "v": volume} for i in range(n)]


class FakeRouter:
    def __init__(self, profiles, eod, search):
        self.profiles, self.eod, self.search = profiles, eod, search

    def get(self, cap, sym=None, **kw):
        table = {"profile": self.profiles, "eod": self.eod, "search": self.search}[cap]
        if sym not in table:
            raise DataUnavailable(cap, sym, [])
        return Res(table[sym])


SAMSUNG = "Samsung Electronics Co., Ltd."


def world():
    return FakeRouter(
        profiles={"SSU": {"name": "SIGNA Sports United N.V.", "exchange": "NYSE"},
                  "SSU.F": {"name": SAMSUNG, "exchange": "FRA"},
                  "005930.KS": {"name": SAMSUNG, "exchange": "KSC"},
                  "AAPL": {"name": "Apple Inc.", "exchange": "NASDAQ"},
                  "DEAD": {"name": "Dead Corp", "exchange": "NYSE"}},
        eod={"SSU": bars(1e-6, 0),            # barras-fantasma (Tiingo)
             "SSU.F": bars(3420, 500), "005930.KS": bars(206000, 1e7), "AAPL": bars(356, 5e7),
             "DEAD": bars(1e-6, 0), "ABC.F": bars(10, 100), "ABC.T": bars(900, 1000)},
        search={"SSU": [{"symbol": "SSU.F", "exchange": "FRA", "type": "EQUITY", "name": SAMSUNG},
                        {"symbol": "SSUMY", "exchange": "PNK", "type": "EQUITY", "name": "Sumitomo Corporation"}],
                SAMSUNG: [{"symbol": "005930.KS", "exchange": "KSC", "type": "EQUITY", "name": SAMSUNG},
                          {"symbol": "SSU.F", "exchange": "FRA", "type": "EQUITY", "name": SAMSUNG}],
                "SIGNA Sports United N.V.": [], "Dead Corp": [], "DEAD": [],
                "ABC": [{"symbol": "ABC.F", "exchange": "FRA", "type": "EQUITY", "name": "Alpha Co"},
                        {"symbol": "ABC.T", "exchange": "JPX", "type": "EQUITY", "name": "Beta KK"}],
                "Alpha Co": [], "Beta KK": [{"symbol": "ABC.T", "exchange": "JPX", "type": "EQUITY", "name": "Beta KK"}]},
    )


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        self.res = P.Resolver(world())

    def test_dead_us_symbol_falls_back_to_exact_code_elsewhere(self):
        sym, prof, note = self.res.resolve("SSU")
        self.assertEqual(sym, "005930.KS")
        self.assertIn("SIGNA", note)
        self.assertIn("Samsung", note)

    def test_secondary_listing_maps_to_primary(self):
        sym, _, note = self.res.resolve("SSU.F")
        self.assertEqual(sym, "005930.KS")
        self.assertIn("cotação secundária", note)

    def test_alive_primary_is_respected(self):
        self.assertEqual(self.res.resolve("AAPL")[:1], ("AAPL",))
        self.assertIsNone(self.res.resolve("AAPL")[2])

    def test_ghost_bars_are_not_alive(self):
        self.assertFalse(self.res.alive("SSU")[0])
        self.assertTrue(self.res.alive("AAPL")[0])

    def test_ambiguous_exact_code(self):
        with self.assertRaises(ValueError) as e:
            self.res.resolve("ABC")
        self.assertIn("ambíguo", str(e.exception))

    def test_dead_without_alternative_stops(self):
        with self.assertRaises(ValueError) as e:
            self.res.resolve("DEAD")
        self.assertIn("não encontrei nenhuma cotação ativa", str(e.exception))


class BotCommandTests(unittest.TestCase):
    def test_symbol_from_command(self):
        self.assertEqual(bot.symbol_from_command("005930_KS"), "005930.KS")
        self.assertEqual(bot.symbol_from_command("AAPL"), "AAPL")

    def test_profile_error_lists_tappable_options(self):
        txt = bot.profile_error_text("ABC", "ValueError: 'ABC' é ambíguo — escolhe uma: Alpha Co → ABC.F; Beta KK → ABC.T")
        self.assertIn("/run_ABC_F", txt)
        self.assertIn("/run_ABC_T", txt)


if __name__ == "__main__":
    unittest.main()
