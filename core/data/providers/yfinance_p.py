from datetime import date, timedelta

from .base import Provider, bars_from_df, now_iso, num, pct, unix_to_iso


def trailing_yield(dividends, price: float | None, now=None) -> float | None:
    """Dividend yield (%) com base nos dividendos pagos nos últimos 365 dias. None se não houver histórico."""
    import pandas as pd
    if dividends is None or len(dividends) == 0 or not price:
        return None
    now = now or pd.Timestamp.now(tz=dividends.index.tz)
    paid = float(dividends[dividends.index >= now - pd.Timedelta(days=365)].sum())
    return round(paid / price * 100, 2)


class YFinance(Provider):
    name = "yfinance"
    capabilities = frozenset({"quote", "eod", "intraday", "profile", "news", "analyst_recs", "price_targets",
                              "upgrades", "calendar", "search", "fx", "financials"})

    ROWS = {  # campo normalizado -> nomes possíveis no yfinance (verificados na Fase 1)
        "income": {"revenue": ["Total Revenue", "Operating Revenue"], "gross_profit": ["Gross Profit"],
                   "operating_income": ["Operating Income", "Total Operating Income As Reported"],
                   "net_income": ["Net Income", "Net Income Common Stockholders"], "ebit": ["EBIT"],
                   "ebitda": ["EBITDA", "Normalized EBITDA"], "eps_diluted": ["Diluted EPS"],
                   "interest_expense": ["Interest Expense"]},
        "balance": {"total_assets": ["Total Assets"], "total_liabilities": ["Total Liabilities Net Minority Interest"],
                    "current_assets": ["Current Assets"], "current_liabilities": ["Current Liabilities"],
                    "long_term_debt": ["Long Term Debt"], "total_debt": ["Total Debt"],
                    "cash": ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"],
                    "equity": ["Stockholders Equity", "Common Stock Equity"], "retained_earnings": ["Retained Earnings"],
                    "shares": ["Ordinary Shares Number", "Share Issued"], "working_capital": ["Working Capital"]},
        "cashflow": {"operating_cash_flow": ["Operating Cash Flow"], "capex": ["Capital Expenditure"],
                     "free_cash_flow": ["Free Cash Flow"], "dividends_paid": ["Cash Dividends Paid"],
                     "buybacks": ["Repurchase Of Capital Stock"]},
    }
    INFO = {"trailing_pe": "trailingPE", "forward_pe": "forwardPE", "price_to_book": "priceToBook",
            "ev_to_ebitda": "enterpriseToEbitda", "profit_margin": "profitMargins", "gross_margin": "grossMargins",
            "operating_margin": "operatingMargins", "roe": "returnOnEquity", "debt_to_equity": "debtToEquity",
            "beta": "beta", "dividend_yield_pct": "dividendYield", "enterprise_value": "enterpriseValue",
            "market_cap": "marketCap", "revenue_growth": "revenueGrowth", "earnings_growth": "earningsGrowth",
            "trailing_eps": "trailingEps", "forward_eps": "forwardEps"}

    def financials(self, s, years: int = 4):
        """Demonstrações anuais (mais recente primeiro) + rácios do info. Valores na moeda de reporte."""
        t = self._t(s)
        frames = {"income": t.income_stmt, "balance": t.balance_sheet, "cashflow": t.cashflow}
        inc = frames["income"]
        if inc is None or inc.empty:
            return None
        yrs = [c.year for c in list(inc.columns)[:years]]
        out = {"fiscal_years": yrs}
        for stmt, fields in self.ROWS.items():
            df = frames[stmt]
            by_year = {c.year: c for c in df.columns} if df is not None and not df.empty else {}
            block = {}
            for field_name, names in fields.items():
                row = next((n for n in names if df is not None and n in df.index), None)
                block[field_name] = [num(df.at[row, by_year[y]]) if row and y in by_year else None for y in yrs]
            out[stmt] = block
        info = t.info or {}
        out["ratios"] = {k: num(info.get(v)) for k, v in self.INFO.items()}
        # o 'dividendYield' do Yahoo vem por vezes errado (Samsung: 8,93% vs ~3% efetivamente pago em 12 meses):
        # usa o dividendo pago nos últimos 12 meses; o valor do Yahoo fica só para comparação
        try:
            ty = trailing_yield(t.dividends, num(info.get("currentPrice")) or num(t.fast_info["lastPrice"]))
        except Exception:
            ty = None
        if ty is not None:
            out["ratios"]["dividend_yield_yahoo_pct"] = out["ratios"]["dividend_yield_pct"]
            out["ratios"]["dividend_yield_pct"] = ty
        out["shares"] = {"outstanding": num(info.get("sharesOutstanding")), "float": num(info.get("floatShares"))}
        out["currency"] = info.get("financialCurrency") or info.get("currency")
        return out

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
        ftd = info.get("firstTradeDateMilliseconds")
        return {"name": name, "exchange": fi["exchange"], "currency": fi["currency"],
                "sector": info.get("sector"), "industry": info.get("industry"), "country": info.get("country"),
                "market_cap": num(fi["marketCap"]), "quote_type": info.get("quoteType"),
                "first_trade_date": unix_to_iso(ftd, ms=True)[:10] if ftd else None,
                "shares_outstanding": num(info.get("sharesOutstanding")), "float_shares": num(info.get("floatShares")),
                "summary": (info.get("longBusinessSummary") or "")[:600] or None}

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
        rows = [{"period": r["period"], "strong_buy": int(r["strongBuy"]), "buy": int(r["buy"]),
                 "hold": int(r["hold"]), "sell": int(r["sell"]), "strong_sell": int(r["strongSell"])}
                for _, r in df.iterrows()]
        cur = next((r for r in rows if r["period"] == "0m"), rows[0])
        return {**cur, "history": rows}

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
