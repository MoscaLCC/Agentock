import unittest

from core.data.http import ProviderError
from core.data.markets import base_code, calendar_code, market_of
from core.data.providers.base import Provider
from core.data.providers.keyed import EODHD, ITick
from core.data.router import DataUnavailable, Router
from core.data.store import Store


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


class Fake(Provider):
    def __init__(self, name, result=None, error=None, caps=("quote", "news")):
        self.name, self.result, self.error = name, result, error
        self.capabilities = frozenset(caps)
        self.calls = 0

    def configured(self):
        return True

    def call(self, capability, symbol, **params):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def cfg(**limits):
    return {
        "providers": {n: {"limits": l} for n, l in limits.items()},
        "routes": {"quote": {"US": ["a", "b"], "default": ["b"]}, "news": {"default": ["a", "b"]}},
        "merge": ["news"], "ttl": {"quote": 60, "news": 60}, "blocked_days": 7, "cooldown_seconds": 120,
    }


class MarketTests(unittest.TestCase):
    def test_market_of(self):
        self.assertEqual(market_of("AAPL"), "US")
        self.assertEqual(market_of("0700.HK"), "HK")
        self.assertEqual(market_of("600519.SS"), "CN")
        self.assertEqual(market_of("005930.KS"), "KR")
        self.assertEqual(market_of("247540.KQ"), "KR")
        self.assertEqual(market_of("ASML.AS"), "EU")
        self.assertEqual(market_of("^GSPC"), "INDEX")
        self.assertEqual(market_of("ES=F"), "FUT")

    def test_calendar_and_codes(self):
        self.assertEqual(calendar_code("300750.SZ"), "XSHG")
        self.assertEqual(calendar_code("AAPL"), "XNYS")
        self.assertEqual(base_code("0700.HK"), "0700")

    def test_provider_symbol_mapping(self):
        self.assertEqual(EODHD()._sym("600519.SS"), "600519.SHG")
        self.assertEqual(EODHD()._sym("005930.KS"), "005930.KO")
        self.assertEqual(EODHD()._sym("AAPL"), "AAPL.US")
        self.assertEqual(ITick._region_code("0700.HK"), ("HK", "700"))
        self.assertEqual(ITick._region_code("300750.SZ"), ("SZ", "300750"))


class RouterTests(unittest.TestCase):
    def make(self, pa, pb, limits=None):
        self.clock = Clock()
        return Router(cfg(**(limits or {})), Store(":memory:", clock=self.clock), {"a": pa, "b": pb})

    def test_priority_and_cache(self):
        a, b = Fake("a", {"price": 1}), Fake("b", {"price": 2})
        r = self.make(a, b)
        self.assertEqual(r.get("quote", "AAPL").provider, "a")
        self.assertTrue(r.get("quote", "AAPL").cached)
        self.assertEqual(a.calls, 1)

    def test_market_route(self):
        a, b = Fake("a", {"price": 1}), Fake("b", {"price": 2})
        self.assertEqual(self.make(a, b).get("quote", "0700.HK").provider, "b")

    def test_blocked_is_remembered(self):
        a, b = Fake("a", error=ProviderError("blocked", "402")), Fake("b", {"price": 2})
        r = self.make(a, b)
        self.assertEqual(r.get("quote", "AAPL").provider, "b")
        r.get("quote", "AAPL", use_cache=False)
        self.assertEqual(a.calls, 1)  # não volta a gastar quota no 'a'

    def test_quota_exhausted_falls_through(self):
        a, b = Fake("a", {"price": 1}), Fake("b", {"price": 2})
        r = self.make(a, b, limits={"a": {"per_minute": 1}})
        r.get("quote", "AAPL")
        self.assertEqual(r.get("quote", "MSFT").provider, "b")
        self.clock.t += 61
        self.assertEqual(r.get("quote", "NVDA").provider, "a")

    def test_rate_limit_cooldown(self):
        a, b = Fake("a", error=ProviderError("quota", "429")), Fake("b", {"price": 2})
        r = self.make(a, b)
        r.get("quote", "AAPL")
        r.get("quote", "MSFT")
        self.assertEqual(a.calls, 1)  # em pausa depois do 429

    def test_empty_falls_through(self):
        a, b = Fake("a", None), Fake("b", {"price": 2})
        self.assertEqual(self.make(a, b).get("quote", "AAPL").provider, "b")

    def test_merge_dedupes_news(self):
        n1 = [{"title": "X", "url": "https://x.com/a?utm=1", "published_at": "2026-11-14T10:00:00Z"}]
        n2 = [{"title": "X", "url": "https://x.com/a", "published_at": "2026-11-14T10:00:00Z"},
              {"title": "Y", "url": "https://y.com/b", "published_at": "2026-11-14T11:00:00Z"}]
        res = self.make(Fake("a", n1), Fake("b", n2)).get("news", "AAPL")
        self.assertEqual([n["title"] for n in res.data], ["Y", "X"])
        self.assertEqual(res.provider, "a+b")

    def test_all_fail(self):
        a, b = Fake("a", error=ProviderError("error", "x")), Fake("b", None)
        r = self.make(a, b)
        with self.assertRaises(DataUnavailable):
            r.get("quote", "AAPL")


if __name__ == "__main__":
    unittest.main()
