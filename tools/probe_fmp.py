"""Fase 0: o que o plano FMP desta chave cobre, por endpoint e por mercado.

Uso: python tools/probe_fmp.py
Gasta ~60 chamadas (plano grátis: 250/dia).
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core.env  # noqa: E402,F401

BASE = "https://financialmodelingprep.com/stable/"

# endpoint -> query (sem symbol); {s} = símbolo
FULL = {
    "profile": "profile?symbol={s}",
    "quote": "quote?symbol={s}",
    "eod": "historical-price-eod/full?symbol={s}&from=2026-10-01",
    "intraday_5min": "historical-chart/5min?symbol={s}",
    "news_stock": "news/stock?symbols={s}&limit=5",
    "peers": "stock-peers?symbol={s}",
    "grades": "grades?symbol={s}",
    "grades_consensus": "grades-consensus?symbol={s}",
    "pt_consensus": "price-target-consensus?symbol={s}",
    "pt_summary": "price-target-summary?symbol={s}",
    "ratings_snapshot": "ratings-snapshot?symbol={s}",
    "estimates": "analyst-estimates?symbol={s}&period=annual&limit=1",
    "financial_scores": "financial-scores?symbol={s}",
    "key_metrics_ttm": "key-metrics-ttm?symbol={s}",
    "ratios_ttm": "ratios-ttm?symbol={s}",
    "income": "income-statement?symbol={s}&limit=1",
    "revenue_segments": "revenue-product-segmentation?symbol={s}",
    "dcf": "discounted-cash-flow?symbol={s}",
    "earnings": "earnings?symbol={s}",
}
GLOBAL = {
    "screener": "company-screener?marketCapMoreThan=500000000000&limit=5",
    "market_hours": "exchange-market-hours?exchange=NASDAQ",
}
SHORT = ["profile", "quote", "eod", "news_stock", "grades", "pt_consensus", "financial_scores", "key_metrics_ttm"]
NON_US = ["ASML.AS", "7203.T", "0700.HK", "600519.SS", "005930.KS"]


def call(path: str, key: str) -> str:
    url = f"{BASE}{path}{'&' if '?' in path else '?'}apikey={key}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("Error Message", "")
        except Exception:
            msg = ""
        return f"HTTP {e.code} {msg[:70]}"
    except Exception as e:
        return f"ERRO {type(e).__name__}"
    if isinstance(d, dict) and ("Error Message" in d or "message" in d):
        return f"BLOQ {str(d.get('Error Message') or d.get('message'))[:70]}"
    if isinstance(d, dict) and "historical" in d:
        d = d["historical"]
    n = len(d) if isinstance(d, (list, dict)) else 1
    return f"ok({n})" if n else "vazio"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    key = os.environ.get("FMP_API_KEY")
    if not key:
        sys.exit("Falta FMP_API_KEY no .env")
    print("== AAPL (todos os endpoints) ==")
    for name, q in FULL.items():
        print(f"{name:18} {call(q.format(s='AAPL'), key)}")
    print("== globais ==")
    for name, q in GLOBAL.items():
        print(f"{name:18} {call(q, key)}")
    for t in NON_US:
        print(f"== {t} ==")
        for name in SHORT:
            print(f"{name:18} {call(FULL[name].format(s=t), key)}")


if __name__ == "__main__":
    main()
