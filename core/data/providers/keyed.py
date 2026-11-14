"""Fornecedores com chave (API REST). Endpoints verificados com tools/probe_*.py, salvo nota."""
import csv
import io
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..http import ProviderError, fetch
from ..markets import base_code, market_of, suffix
from .base import Provider, bars_from_records, days_ago, now_iso, num, pct, unix_to_iso


def _qs(**q) -> str:
    return urllib.parse.urlencode({k: v for k, v in q.items() if v is not None})


class FMP(Provider):
    name, env = "fmp", ("FMP_API_KEY",)
    capabilities = frozenset({"quote", "profile", "eod", "price_targets", "upgrades", "peers", "scores", "dcf"})
    BASE = "https://financialmodelingprep.com/stable/"

    def _get(self, path, **q):
        return fetch(f"{self.BASE}{path}?{_qs(**q, apikey=self.key())}")

    def quote(self, s):
        d = (self._get("quote", symbol=s) or [None])[0]
        return d and {"price": num(d.get("price")), "prev_close": num(d.get("previousClose")),
                      "change_pct": num(d.get("changePercentage")), "currency": None,
                      "ts": unix_to_iso(d.get("timestamp")) or now_iso()}

    def profile(self, s):
        d = (self._get("profile", symbol=s) or [None])[0]
        return d and {"name": d.get("companyName"), "exchange": d.get("exchange"), "currency": d.get("currency"),
                      "sector": d.get("sector"), "industry": d.get("industry"), "country": d.get("country"),
                      "market_cap": num(d.get("marketCap")), "quote_type": "EQUITY",
                      "first_trade_date": d.get("ipoDate"), "shares_outstanding": None, "float_shares": None,
                      "summary": (d.get("description") or "")[:600] or None}

    def scores(self, s):
        d = (self._get("financial-scores", symbol=s) or [None])[0]
        return d and {"altman_z": num(d.get("altmanZScore")), "piotroski": num(d.get("piotroskiScore"))}

    def dcf(self, s):
        d = (self._get("discounted-cash-flow", symbol=s) or [None])[0]
        return d and {"dcf": num(d.get("dcf")), "price": num(d.get("Stock Price")), "date": d.get("date")}

    def eod(self, s, days: int = 365):
        d = self._get("historical-price-eod/full", symbol=s, **{"from": days_ago(days)})
        rows = d.get("historical", []) if isinstance(d, dict) else d
        return bars_from_records(rows, "date")

    def price_targets(self, s):
        d = (self._get("price-target-consensus", symbol=s) or [None])[0]
        return d and {"current": None, "low": num(d.get("targetLow")), "high": num(d.get("targetHigh")),
                      "mean": num(d.get("targetConsensus")), "median": num(d.get("targetMedian"))}

    def upgrades(self, s, limit: int = 30):
        return [{"date": g.get("date"), "firm": g.get("gradingCompany"), "from_grade": g.get("previousGrade"),
                 "to_grade": g.get("newGrade"), "action": g.get("action"), "price_target": None,
                 "prior_price_target": None} for g in (self._get("grades", symbol=s) or [])[:limit]]

    def peers(self, s):
        return [p["symbol"] for p in (self._get("stock-peers", symbol=s) or []) if p.get("symbol")]


class Finnhub(Provider):
    name, env = "finnhub", ("FINNHUB_API_KEY",)
    capabilities = frozenset({"quote", "news", "analyst_recs", "ipo_calendar", "insider"})
    BASE = "https://finnhub.io/api/v1/"

    def _get(self, path, **q):
        return fetch(f"{self.BASE}{path}?{_qs(**q, token=self.key())}")

    def quote(self, s):
        d = self._get("quote", symbol=s)
        if not d or not d.get("c"):
            return None
        return {"price": num(d["c"]), "prev_close": num(d.get("pc")), "change_pct": num(d.get("dp")),
                "currency": "USD", "ts": unix_to_iso(d.get("t"))}

    def news(self, s, days: int = 7, limit: int = 50):
        rows = self._get("company-news", symbol=s, **{"from": days_ago(days), "to": date.today().isoformat()})
        return [{"title": n.get("headline"), "url": n.get("url"), "source": n.get("source"),
                 "published_at": unix_to_iso(n.get("datetime")), "summary": n.get("summary")}
                for n in (rows or [])[:limit] if n.get("headline") and n.get("url")]

    def analyst_recs(self, s):
        rows = self._get("stock/recommendation", symbol=s)
        if not rows:
            return None
        hist = [{"period": r.get("period"), "strong_buy": r.get("strongBuy"), "buy": r.get("buy"),
                 "hold": r.get("hold"), "sell": r.get("sell"), "strong_sell": r.get("strongSell")} for r in rows[:4]]
        return {**hist[0], "history": hist}

    def insider(self, s, months: int = 6):
        d = self._get("stock/insider-sentiment", symbol=s, **{"from": days_ago(months * 31),
                                                                "to": date.today().isoformat()})
        rows = sorted((d or {}).get("data", []), key=lambda r: (r["year"], r["month"]))
        if not rows:
            return None
        avg = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
        return {"months": [{"period": f"{r['year']}-{r['month']:02d}", "change": r.get("change"),
                            "mspr": num(r.get("mspr"))} for r in rows],
                "mspr_avg_3m": avg([r["mspr"] for r in rows[-3:] if r.get("mspr") is not None]),
                "net_change": sum(r.get("change") or 0 for r in rows)}

    def ipo_calendar(self, _=None, days: int = 30):
        d = self._get("calendar/ipo", **{"from": date.today().isoformat(),
                                         "to": (date.today() + timedelta(days=days)).isoformat()})
        return [{"date": i.get("date"), "symbol": i.get("symbol"), "name": i.get("name"),
                 "exchange": i.get("exchange"), "price_range": i.get("price"), "shares": i.get("numberOfShares"),
                 "value": i.get("totalSharesValue"), "status": i.get("status"), "currency": "USD"}
                for i in (d or {}).get("ipoCalendar", [])]


class Alpaca(Provider):
    name, env = "alpaca", ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY")
    capabilities = frozenset({"quote", "intraday", "news"})
    BASE = "https://data.alpaca.markets/"
    TF = {"1m": "1Min", "5m": "5Min", "15m": "15Min", "30m": "30Min", "1h": "1Hour"}

    def _get(self, path, **q):
        h = {"APCA-API-KEY-ID": self.key(0), "APCA-API-SECRET-KEY": self.key(1)}
        return fetch(f"{self.BASE}{path}?{_qs(**q)}", h)

    def quote(self, s):  # snapshot: endpoint não verificado no probe
        d = self._get(f"v2/stocks/{s}/snapshot", feed="iex")
        price = num((d.get("latestTrade") or {}).get("p"))
        prev = num((d.get("prevDailyBar") or {}).get("c"))
        if not price:
            return None
        return {"price": price, "prev_close": prev, "change_pct": pct(price, prev), "currency": "USD",
                "ts": (d.get("latestTrade") or {}).get("t")}

    def intraday(self, s, interval: str = "5m", days: int = 5):
        rows, token = [], None
        for _ in range(5):  # paginação
            d = self._get(f"v2/stocks/{s}/bars", timeframe=self.TF[interval], start=days_ago(days),
                          feed="iex", limit=10000, page_token=token)
            rows += d.get("bars") or []
            token = d.get("next_page_token")
            if not token:
                break
        return bars_from_records(rows, "t", "o", "h", "l", "c", "v", daily=False)

    def news(self, s, limit: int = 50):
        d = self._get("v1beta1/news", symbols=s, limit=min(limit, 50))
        return [{"title": n.get("headline"), "url": n.get("url"), "source": n.get("source"),
                 "published_at": n.get("created_at"), "summary": n.get("summary")} for n in d.get("news", [])]


class Tiingo(Provider):
    name, env = "tiingo", ("TIINGO_API_KEY",)
    capabilities = frozenset({"eod", "intraday"})
    BASE = "https://api.tiingo.com/"

    @staticmethod
    def _sym(s):
        return base_code(s) if market_of(s) == "CN" else s.lower()

    def eod(self, s, days: int = 365):
        rows = fetch(f"{self.BASE}tiingo/daily/{self._sym(s)}/prices?{_qs(startDate=days_ago(days), token=self.key())}")
        return bars_from_records(rows or [], "date")

    def intraday(self, s, interval: str = "5m", days: int = 5):
        freq = interval.replace("m", "min").replace("1h", "1hour")
        rows = fetch(f"{self.BASE}iex/{self._sym(s)}/prices?"
                     f"{_qs(startDate=days_ago(days), resampleFreq=freq, token=self.key())}")
        return bars_from_records(rows or [], "date", daily=False)


class ITick(Provider):
    """Cotação verificada (HK, SH, SZ, KR, JP); kline kType=2 (5 min) verificado em HK."""
    name, env = "itick", ("ITICK_API_KEY",)
    capabilities = frozenset({"quote", "intraday"})
    BASE = "https://api.itick.org/stock/"
    KTYPE = {"1m": 1, "5m": 2, "15m": 3, "30m": 4, "1h": 5}  # só o 2 verificado

    @staticmethod
    def _region_code(s):
        sfx, code = suffix(s), base_code(s)
        region = {".HK": "HK", ".SS": "SH", ".SZ": "SZ", ".KS": "KR", ".KQ": "KR", ".T": "JP"}.get(sfx)
        if not region:
            raise ProviderError("notfound", f"iTick sem região para {s}")
        return region, (str(int(code)) if region == "HK" else code)

    def _get(self, path, **q):
        d = fetch(f"{self.BASE}{path}?{_qs(**q)}", {"accept": "application/json", "token": self.key()})
        if d.get("code") not in (0, None):
            raise ProviderError("error", str(d.get("msg")))
        return d.get("data")

    def quote(self, s):
        region, code = self._region_code(s)
        d = self._get("quote", region=region, code=code)
        return d and {"price": num(d.get("ld")), "prev_close": num(d.get("p")), "change_pct": num(d.get("chp")),
                      "currency": None, "ts": unix_to_iso(d.get("t"), ms=True)}

    def intraday(self, s, interval: str = "5m", days: int = 5):
        region, code = self._region_code(s)
        rows = self._get("kline", region=region, code=code, kType=self.KTYPE[interval], limit=min(80 * days, 500))
        out = [{"t": unix_to_iso(r.get("t"), ms=True), "o": num(r.get("o")), "h": num(r.get("h")),
                "l": num(r.get("l")), "c": num(r.get("c")), "v": num(r.get("v"))} for r in (rows or [])]
        return sorted(out, key=lambda b: b["t"] or "")


class EODHD(Provider):
    name, env = "eodhd", ("EODHD_API_KEY",)
    capabilities = frozenset({"eod", "news"})
    weights = {"news": 5}
    BASE = "https://eodhd.com/api/"
    # verificados: .US .AS .HK .SHG .KO ; restantes segundo a documentação (não verificados)
    SFX = {"": ".US", ".HK": ".HK", ".SS": ".SHG", ".SZ": ".SHE", ".KS": ".KO", ".KQ": ".KQ", ".T": ".TSE",
           ".L": ".LSE", ".DE": ".XETRA", ".AS": ".AS", ".PA": ".PA", ".SW": ".SW", ".MI": ".MI", ".MC": ".MC"}

    def _sym(self, s):
        sfx = suffix(s)
        if sfx not in self.SFX:
            raise ProviderError("notfound", f"EODHD sem mapeamento para {s}")
        return base_code(s) + self.SFX[sfx]

    def eod(self, s, days: int = 365):
        rows = fetch(f"{self.BASE}eod/{self._sym(s)}?{_qs(**{'from': days_ago(days)}, api_token=self.key(), fmt='json')}")
        return bars_from_records(rows or [], "date")

    def news(self, s, limit: int = 20):
        rows = fetch(f"{self.BASE}news?{_qs(s=self._sym(s), limit=limit, api_token=self.key(), fmt='json')}")
        return [{"title": n.get("title"), "url": n.get("link"), "source": "EODHD",
                 "published_at": n.get("date"), "summary": (n.get("content") or "")[:400]} for n in rows or []]


class TwelveData(Provider):
    name, env = "twelvedata", ("TWELVEDATA_API_KEY",)
    capabilities = frozenset({"quote", "fx"})
    BASE = "https://api.twelvedata.com/"

    def quote(self, s):
        d = fetch(f"{self.BASE}quote?{_qs(symbol=s, apikey=self.key())}")
        price = num(d.get("close"))
        return price and {"price": price, "prev_close": num(d.get("previous_close")),
                          "change_pct": num(d.get("percent_change")), "currency": d.get("currency"),
                          "ts": unix_to_iso(d.get("timestamp"))}

    def fx(self, pair: str):
        d = fetch(f"{self.BASE}exchange_rate?{_qs(symbol=pair.upper(), apikey=self.key())}")
        return d.get("rate") and {"pair": pair.upper(), "rate": num(d["rate"]), "ts": unix_to_iso(d.get("timestamp"))}


class AlphaVantage(Provider):
    name, env = "alphavantage", ("ALPHAVANTAGE_API_KEY",)
    capabilities = frozenset({"eod", "ipo_calendar"})
    BASE = "https://www.alphavantage.co/query?"
    SFX = {"": "", ".SS": ".SHH", ".SZ": ".SHZ"}

    def eod(self, s, days: int = 100):
        sfx = suffix(s)
        if sfx not in self.SFX:
            raise ProviderError("notfound", f"Alpha Vantage sem mapeamento para {s}")
        d = fetch(self.BASE + _qs(function="TIME_SERIES_DAILY", symbol=base_code(s) + self.SFX[sfx], apikey=self.key()))
        series = d.get("Time Series (Daily)") or {}
        rows = [{"date": k, "open": v.get("1. open"), "high": v.get("2. high"), "low": v.get("3. low"),
                 "close": v.get("4. close"), "volume": v.get("5. volume")} for k, v in series.items()]
        return bars_from_records(rows, "date")[-days:]

    def ipo_calendar(self, _=None, days: int = 30):
        text = fetch(self.BASE + _qs(function="IPO_CALENDAR", apikey=self.key()), raw=True)
        limit = (date.today() + timedelta(days=days)).isoformat()
        out = []
        for r in csv.DictReader(io.StringIO(text)):
            if not r.get("ipoDate") or r["ipoDate"] > limit:
                continue
            lo, hi = num(r.get("priceRangeLow")), num(r.get("priceRangeHigh"))
            out.append({"date": r["ipoDate"], "symbol": r.get("symbol"), "name": r.get("name"),
                        "exchange": r.get("exchange"), "price_range": f"{lo}-{hi}" if lo and hi else None,
                        "shares": None, "value": None, "status": "expected", "currency": r.get("currency") or "USD"})
        return out


class Marketstack(Provider):
    name, env = "marketstack", ("MARKETSTACK_API_KEY",)
    capabilities = frozenset({"eod"})

    def eod(self, s, days: int = 30):  # só verificado 'eod/latest' para AAPL
        d = fetch(f"https://api.marketstack.com/v2/eod?{_qs(access_key=self.key(), symbols=s, date_from=days_ago(days))}")
        return bars_from_records(d.get("data") or [], "date")


class AkShare(Provider):
    """China A: notícias Eastmoney. Hora vem em hora de Pequim sem fuso → convertida para UTC."""
    name = "akshare"
    capabilities = frozenset({"news"})

    def news(self, s, limit: int = 20):
        if market_of(s) != "CN":
            raise ProviderError("notfound", "akshare só para China A")
        import akshare as ak
        try:
            df = ak.stock_news_em(symbol=base_code(s))
        except Exception as e:  # o Eastmoney limita o IP com exceções próprias
            if "限流" in str(e) or "RateLimit" in type(e).__name__:
                raise ProviderError("quota", str(e)[:120])
            raise
        out = []
        for _, r in df.head(limit).iterrows():
            t = datetime.fromisoformat(str(r["发布时间"])).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            out.append({"title": r["新闻标题"], "url": r["新闻链接"], "source": r["文章来源"],
                        "published_at": t.astimezone(timezone.utc).isoformat(timespec="seconds"),
                        "summary": str(r["新闻内容"])[:400]})
        return out
