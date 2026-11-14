"""Teste real da camada de dados: cada fornecedor no seu endpoint + router a escolher sozinho.

Uso: python tools/smoke_data.py
Usa data/smoke.db (separado) para não deixar bloqueios/cache do teste no sistema. ~30 chamadas.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.data.router import DataUnavailable, Router  # noqa: E402
from core.data.store import Store  # noqa: E402

DIRECT = [  # (fornecedor, capacidade, símbolo, params)
    ("yfinance", "quote", "AAPL", {}), ("yfinance", "calendar", "AAPL", {}), ("yfinance", "search", "Alibaba", {}),
    ("yfinance", "upgrades", "AAPL", {}), ("yfinance", "price_targets", "0700.HK", {}),
    ("yfinance", "analyst_recs", "005930.KS", {}), ("yfinance", "news", "005930.KS", {}),
    ("fmp", "profile", "AAPL", {}), ("fmp", "peers", "AAPL", {}), ("fmp", "price_targets", "AAPL", {}),
    ("fmp", "upgrades", "AAPL", {}),
    ("finnhub", "news", "AAPL", {}), ("finnhub", "analyst_recs", "AAPL", {}), ("finnhub", "ipo_calendar", None, {}),
    ("alpaca", "quote", "AAPL", {}), ("alpaca", "intraday", "AAPL", {}), ("alpaca", "news", "AAPL", {}),
    ("tiingo", "eod", "600519.SS", {"days": 10}), ("tiingo", "intraday", "AAPL", {}),
    ("itick", "quote", "005930.KS", {}), ("itick", "intraday", "0700.HK", {}),
    ("eodhd", "eod", "005930.KS", {"days": 10}),
    ("twelvedata", "fx", "USD/KRW", {}), ("twelvedata", "quote", "AAPL", {}),
    ("alphavantage", "ipo_calendar", None, {}),
    ("marketstack", "eod", "AAPL", {"days": 10}),
    ("akshare", "news", "600519.SS", {}),
]

ROUTED = [("quote", "AAPL"), ("quote", "0700.HK"), ("eod", "600519.SS"), ("news", "AAPL"),
          ("profile", "005930.KS"), ("fx", "USD/JPY"), ("ipo_calendar", None)]


def summary(data) -> str:
    if isinstance(data, list):
        first = json.dumps(data[0], ensure_ascii=False, default=str)[:110] if data else ""
        return f"{len(data)} itens | {first}"
    return json.dumps(data, ensure_ascii=False, default=str)[:140]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    r = Router(store=Store(Path(__file__).resolve().parents[1] / "data" / "smoke.db"))
    print("== fornecedor a fornecedor")
    for name, cap, sym, params in DIRECT:
        if name == "itick":
            time.sleep(8)  # limite por minuto apertado
        data, why = r._try(name, cap, sym, params)
        print(f"  {'OK ' if data else 'XX '} {name:12} {cap:13} {str(sym):10} {summary(data) if data else why}")
    print("== router (escolhe o fornecedor)")
    for cap, sym in ROUTED:
        try:
            res = r.get(cap, sym, use_cache=False)
            print(f"  OK  {cap:13} {str(sym):10} -> {res.provider:28} {summary(res.data)[:90]}")
        except DataUnavailable as e:
            print(f"  XX  {cap:13} {str(sym):10} -> {e}")
    print("== validação cruzada de fechos")
    for s in ["AAPL", "600519.SS", "005930.KS"]:
        print("  ", r.cross_check_close(s))


if __name__ == "__main__":
    main()
