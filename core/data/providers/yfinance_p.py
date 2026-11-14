from datetime import date, timedelta

from .base import Provider, bars_from_df, now_iso, num, pct


class YFinance(Provider):
    name = "yfinance"
    capabilities = frozenset({"quote", "eod", "intraday", "profile", "news", "analyst_recs", "price_targets",
                              "upgrades", "calendar", "search", "fx"})

    @staticmethod
    def _t(symbol):
        import yfinance as yf
        return yf.Ticker(symbol)

    def quote(self, s):
        fi = self._t(s).fast_info
        price, prev = num(fi["lastPrice"]), num(fi["previousClose"])
        if not price:
            return None
        return {"price": price, "prev_close": prev, "change_pct": pct(price, prev),
                "currency": fi["currency"], "ts": now_iso()}

    def eod(self, s, days: int = 365):
        start = (date.today() - timedelta(days=days)).isoformat()
        return bars_from_df(self._t(s).history(start=start, auto_adjust=False), daily=True)

    def intraday(self, s, interval: str = "5m", days: int = 5):
        period = "1d" if days <= 1 else "5d" if days <= 5 else "1mo"
        return bars_from_df(self._t(s).history(period=period, interval=interval), daily=False)

    def profile(self, s):
        t = self._t(s)
        info, fi = t.info or {}, t.fast_info
        name = info.get("longName") or info.get("shortName")
        if not name:
            return None
        return {"name": name, "exchange": fi["exchange"], "currency": fi["currency"],
                "sector": info.get("sector"), "industry": info.get("industry"), "country": info.get("country"),
                "market_cap": num(fi["marketCap"])}

    def news(self, s, limit: int = 20):
        out = []
        for n in (self._t(s).news or [])[:limit]:
            c = n.get("content", n)
            url = (c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url")
            if not (c.get("title") and url):
                continue
            out.append({"title": c["title"], "url": url, "source": (c.get("provider") or {}).get("displayName"),
                        "published_at": c.get("pubDate"), "summary": c.get("summary") or c.get("description")})
        return out

    def analyst_recs(self, s):
        df = self._t(s).recommendations
        if df is None or df.empty:
            return None
        cur = df[df["period"] == "0m"]
        r = (cur if not cur.empty else df).iloc[0]
        return {"period": r["period"], "strong_buy": int(r["strongBuy"]), "buy": int(r["buy"]),
                "hold": int(r["hold"]), "sell": int(r["sell"]), "strong_sell": int(r["strongSell"])}

    def price_targets(self, s):
        d = self._t(s).analyst_price_targets or {}
        if not d.get("mean"):
            return None
        return {k: num(d.get(k)) for k in ("current", "low", "high", "mean", "median")}

    def upgrades(self, s, limit: int = 30):
        df = self._t(s).upgrades_downgrades
        if df is None or df.empty:
            return []
        out = []
        for idx, r in df.head(limit).iterrows():
            out.append({"date": str(idx)[:10], "firm": r.get("Firm"), "from_grade": r.get("FromGrade") or None,
                        "to_grade": r.get("ToGrade"), "action": r.get("Action"),
                        "price_target": num(r.get("currentPriceTarget")) or None,
                        "prior_price_target": num(r.get("priorPriceTarget")) or None})
        return out

    def calendar(self, s):
        cal = self._t(s).calendar or {}
        if not cal:
            return None
        d = lambda v: str(v) if v is not None else None  # noqa: E731
        return {"earnings_dates": [str(x) for x in cal.get("Earnings Date", [])],
                "ex_dividend": d(cal.get("Ex-Dividend Date")), "dividend_date": d(cal.get("Dividend Date")),
                "eps_estimate_avg": num(cal.get("Earnings Average")),
                "revenue_estimate_avg": num(cal.get("Revenue Average"))}

    def search(self, query, limit: int = 10):
        import yfinance as yf
        return [{"symbol": q.get("symbol"), "exchange": q.get("exchange"),
                 "name": q.get("longname") or q.get("shortname"), "type": q.get("quoteType")}
                for q in yf.Search(query, max_results=limit).quotes]

    def fx(self, pair: str):
        base, quote = pair.upper().split("/")
        rate = num(self._t(f"{base}{quote}=X").fast_info["lastPrice"])
        return {"pair": pair.upper(), "rate": rate, "ts": now_iso()} if rate else None
