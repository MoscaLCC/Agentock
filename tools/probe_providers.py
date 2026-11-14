"""Fase 0: cobertura dos fornecedores complementares (os que tiverem chave no .env).

Uso: python tools/probe_providers.py [fornecedor ...]
     fornecedores: gurufocus tiingo itick finnhub alphavantage alpaca twelvedata eodhd marketstack
Chamadas por fornecedor (respeita quotas pequenas): gurufocus 3/~100 mês, tiingo 5/50 hora, itick 6, finnhub 8,
alphavantage 4/25 dia, alpaca 3, twelvedata 5/800 dia, eodhd ~10/20 dia, marketstack 2/100.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core.env  # noqa: E402,F401

E = os.environ.get
TODAY = date.today()
WEEK_AGO = (TODAY - timedelta(days=7)).isoformat()


def size(d) -> str:
    if isinstance(d, list):
        return f"ok({len(d)})" if d else "vazio"
    if isinstance(d, dict):
        for k in ("data", "feed", "bars", "news", "values", "results"):
            if isinstance(d.get(k), list):
                return f"ok({len(d[k])})" if d[k] else "vazio"
        for k, v in d.items():
            if k.startswith("Time Series") and isinstance(v, dict):
                return f"ok({len(v)})"
        return f"ok({len(d)} campos)" if d else "vazio"
    return "ok"


def blocked(d):
    if not isinstance(d, dict):
        return None
    for k in ("Information", "Note", "Error Message", "error"):
        if d.get(k):
            v = d[k]
            return str(v.get("message", v) if isinstance(v, dict) else v)
    if d.get("status") == "error" or (isinstance(d.get("code"), int) and d["code"] >= 400):
        return str(d.get("message"))
    return None


def get(url: str, headers: dict | None = None) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Agentock/0.1", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
            msg = blocked(body) or body.get("message", "")
        except Exception:
            msg = ""
        return f"HTTP {e.code} {str(msg)[:70]}"
    except Exception as e:
        return f"ERRO {type(e).__name__}: {str(e)[:60]}"
    b = blocked(d)
    return f"BLOQ {b[:80]}" if b else size(d)


def finnhub(k):
    u = "https://finnhub.io/api/v1/"
    t = f"&token={k}"
    return {
        "quote AAPL": get(f"{u}quote?symbol=AAPL{t}"),
        "quote 0700.HK": get(f"{u}quote?symbol=0700.HK{t}"),
        "quote 005930.KS": get(f"{u}quote?symbol=005930.KS{t}"),
        "company-news AAPL": get(f"{u}company-news?symbol=AAPL&from={WEEK_AGO}&to={TODAY}{t}"),
        "company-news 0700.HK": get(f"{u}company-news?symbol=0700.HK&from={WEEK_AGO}&to={TODAY}{t}"),
        "recommendation AAPL": get(f"{u}stock/recommendation?symbol=AAPL{t}"),
        "metric 005930.KS": get(f"{u}stock/metric?symbol=005930.KS&metric=all{t}"),
        "insider-sentiment AAPL": get(f"{u}stock/insider-sentiment?symbol=AAPL&from=2026-01-01&to={TODAY}{t}"),
    }


def alphavantage(k):
    u = f"https://www.alphavantage.co/query?apikey={k}&function="
    return {
        "GLOBAL_QUOTE AAPL": get(f"{u}GLOBAL_QUOTE&symbol=AAPL"),
        "NEWS_SENTIMENT AAPL": get(f"{u}NEWS_SENTIMENT&tickers=AAPL&limit=10"),
        "DAILY 600519.SHH": get(f"{u}TIME_SERIES_DAILY&symbol=600519.SHH"),
        "OVERVIEW AAPL": get(f"{u}OVERVIEW&symbol=AAPL"),
    }


def alpaca(key_id, secret):
    h = {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret}
    u = "https://data.alpaca.markets/"
    return {
        "bars 5Min AAPL (iex)": get(f"{u}v2/stocks/AAPL/bars?timeframe=5Min&start={WEEK_AGO}&feed=iex&limit=100", h),
        "latest quote AAPL (iex)": get(f"{u}v2/stocks/AAPL/quotes/latest?feed=iex", h),
        "news AAPL": get(f"{u}v1beta1/news?symbols=AAPL&limit=10", h),
    }


def twelvedata(k):
    u = "https://api.twelvedata.com/"
    t = f"&apikey={k}"
    return {
        "quote AAPL": get(f"{u}quote?symbol=AAPL{t}"),
        "time_series 5min AAPL": get(f"{u}time_series?symbol=AAPL&interval=5min&outputsize=50{t}"),
        "quote 0700 HKEX": get(f"{u}quote?symbol=0700&exchange=HKEX{t}"),
        "quote 005930 KRX": get(f"{u}quote?symbol=005930&exchange=KRX{t}"),
        "exchange_rate USD/KRW": get(f"{u}exchange_rate?symbol=USD/KRW{t}"),
    }


def eodhd(k):
    u = "https://eodhd.com/api/"
    t = f"api_token={k}&fmt=json&from={WEEK_AGO}"
    return {s: get(f"{u}eod/{s}?{t}") for s in ["AAPL.US", "ASML.AS", "0700.HK", "600519.SHG", "005930.KO"]} | {
        "news AAPL.US": get(f"{u}news?s=AAPL.US&limit=3&api_token={k}&fmt=json"),
    }


def marketstack(k):
    u = "https://api.marketstack.com/v2/eod/latest?access_key="
    return {
        "eod AAPL": get(f"{u}{k}&symbols=AAPL"),
        "eod 005930.XKRX": get(f"{u}{k}&symbols=005930.XKRX"),
    }


def tiingo(k):
    u = "https://api.tiingo.com/"
    t = f"token={k}"
    return {
        "daily AAPL": get(f"{u}tiingo/daily/aapl/prices?startDate={WEEK_AGO}&{t}"),
        "meta 600519 (China?)": get(f"{u}tiingo/daily/600519?{t}"),
        "daily 600519": get(f"{u}tiingo/daily/600519/prices?startDate={WEEK_AGO}&{t}"),
        "news AAPL": get(f"{u}tiingo/news?tickers=aapl&limit=10&{t}"),
        "iex 5min AAPL": get(f"{u}iex/aapl/prices?startDate={WEEK_AGO}&resampleFreq=5min&{t}"),
    }


def itick(k):
    # endpoints segundo github.com/itick-org/docs.en (não verificado) — o probe confirma
    h = {"accept": "application/json", "token": k}
    u = "https://api.itick.org/stock/"
    out = {f"quote {r}:{c}": get(f"{u}quote?region={r}&code={c}", h)
           for r, c in [("HK", "700"), ("SH", "600519"), ("SZ", "300750"), ("KR", "005930"), ("JP", "7203")]}
    out["kline 5min HK:700"] = get(f"{u}kline?region=HK&code=700&kType=2&limit=50", h)
    return out


def gurufocus(k):
    # formato segundo a documentação antiga da API pública (não verificado) — 3 chamadas da quota mensal
    u = f"https://api.gurufocus.com/public/user/{k}/stock/"
    return {
        "summary AAPL": get(f"{u}AAPL/summary"),
        "summary HKSE:00700": get(f"{u}{urllib.parse.quote('HKSE:00700')}/summary"),
        "gurus AAPL": get(f"{u}AAPL/gurus"),
    }


PROVIDERS = {
    "gurufocus": (lambda: E("GURUFOCUS_API_TOKEN"), gurufocus),
    "tiingo": (lambda: E("TIINGO_API_KEY"), tiingo),
    "itick": (lambda: E("ITICK_API_KEY"), itick),
    "finnhub": (lambda: E("FINNHUB_API_KEY"), finnhub),
    "alphavantage": (lambda: E("ALPHAVANTAGE_API_KEY"), alphavantage),
    "alpaca": (lambda: E("ALPACA_API_KEY_ID") and E("ALPACA_API_SECRET_KEY") and
               (E("ALPACA_API_KEY_ID"), E("ALPACA_API_SECRET_KEY")), alpaca),
    "twelvedata": (lambda: E("TWELVEDATA_API_KEY"), twelvedata),
    "eodhd": (lambda: E("EODHD_API_KEY"), eodhd),
    "marketstack": (lambda: E("MARKETSTACK_API_KEY"), marketstack),
}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    for name in sys.argv[1:] or PROVIDERS:
        creds_fn, fn = PROVIDERS[name]
        creds = creds_fn()
        if not creds:
            print(f"== {name}: sem chave no .env, ignorado")
            continue
        print(f"== {name}")
        res = fn(*creds) if isinstance(creds, tuple) else fn(creds)
        for k, v in res.items():
            print(f"  {k:28} {v}")


if __name__ == "__main__":
    main()
