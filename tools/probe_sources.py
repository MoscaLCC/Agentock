"""Fase 0: testa a cobertura das fontes de dados grátis por mercado.

Uso: python tools/probe_sources.py [TICKER ...]
Sem argumentos usa um ticker de cada mercado coberto.
"""
import json
import sys
import urllib.parse
import urllib.request

import yfinance as yf

DEFAULT = ["AAPL", "ASML.AS", "7203.T", "0700.HK", "600519.SS", "300750.SZ", "005930.KS", "247540.KQ"]


def check(f):
    try:
        v = f()
        if v is None:
            return "None"
        if hasattr(v, "empty"):
            return "vazio" if v.empty else f"ok({len(v)})"
        if isinstance(v, (list, dict)):
            return f"ok({len(v)})" if v else "vazio"
        return f"ok({str(v)[:30]})"
    except Exception as e:
        return f"ERRO {type(e).__name__}: {str(e)[:60]}"


def probe_yf(t: str) -> dict:
    tk = yf.Ticker(t)
    return {
        "eod_1y": check(lambda: tk.history(period="1y")),
        "intraday_5m": check(lambda: tk.history(period="5d", interval="5m")),
        "mcap": check(lambda: tk.fast_info["marketCap"]),
        "exchange": check(lambda: tk.fast_info["exchange"]),
        "currency": check(lambda: tk.fast_info["currency"]),
        "news": check(lambda: tk.news),
        "calendar": check(lambda: tk.calendar),
        "price_targets": check(lambda: tk.analyst_price_targets),
        "recommendations": check(lambda: tk.recommendations),
        "upgrades_downgrades": check(lambda: tk.upgrades_downgrades),
        "income_stmt": check(lambda: tk.income_stmt),
        "sector": check(lambda: tk.info.get("sector")),
    }


def probe_akshare() -> str:
    try:
        import akshare as ak
        return f"stock_news_em(600519): {len(ak.stock_news_em(symbol='600519'))} notícias"
    except Exception as e:
        return f"ERRO {type(e).__name__}: {str(e)[:80]}"


def probe_gdelt() -> str:
    qs = urllib.parse.urlencode({"query": '"Samsung Electronics"', "mode": "ArtList", "format": "json",
                                 "timespan": "24h", "maxrecords": 10})
    try:
        with urllib.request.urlopen(f"https://api.gdeltproject.org/api/v2/doc/doc?{qs}", timeout=30) as r:
            return f"{len(json.load(r).get('articles', []))} artigos"
    except Exception as e:
        return f"ERRO {type(e).__name__}: {str(e)[:80]}"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for t in sys.argv[1:] or DEFAULT:
        print(t, json.dumps(probe_yf(t), ensure_ascii=False))
    print("akshare:", probe_akshare())
    print("GDELT:", probe_gdelt())
