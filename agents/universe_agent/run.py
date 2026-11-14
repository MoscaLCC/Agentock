"""Universo: top N empresas por market cap, todos os mercados.

Fontes (por ordem):
  1. FMP (env FMP_API_KEY) — endpoint company-screener  [NÃO VERIFICADO contra a API real]
  2. data/universe.csv (colunas: symbol,name,exchange,marketCap) — manual / fallback
Resultado em cache em data/universe.json (reutilizado se tiver menos de max_age_days).

Limitações conhecidas: a deduplicação de dupla cotação/ADR é só por nome de empresa, e a
market cap pode vir em moedas locais diferentes consoante a fonte (não normalizado).
"""
import csv
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data"
CACHE = DATA / "universe.json"
CSV = DATA / "universe.csv"


def _from_fmp(top_n: int) -> list[dict]:
    key = os.environ["FMP_API_KEY"]
    qs = urllib.parse.urlencode({
        "marketCapMoreThan": 1_000_000_000, "isActivelyTrading": "true",
        "isEtf": "false", "isFund": "false", "limit": top_n * 3, "apikey": key,
    })
    url = f"https://financialmodelingprep.com/stable/company-screener?{qs}"
    with urllib.request.urlopen(url, timeout=60) as r:
        rows = json.load(r)
    return [{"symbol": x["symbol"], "name": x.get("companyName", ""),
             "exchange": x.get("exchangeShortName") or x.get("exchange", ""),
             "marketCap": x.get("marketCap") or 0} for x in rows]


def _from_csv() -> list[dict]:
    with open(CSV, encoding="utf-8", newline="") as f:
        return [{"symbol": r["symbol"], "name": r.get("name", ""), "exchange": r.get("exchange", ""),
                 "marketCap": float(r.get("marketCap") or 0)} for r in csv.DictReader(f)]


def _dedupe_top(rows: list[dict], top_n: int) -> list[dict]:
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: r["marketCap"], reverse=True):
        k = (r["name"] or r["symbol"]).strip().lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
        if len(out) == top_n:
            break
    return out


def run(top_n: int = 500, refresh: bool = False, max_age_days: float = 1.0) -> list[dict]:
    if not refresh and CACHE.exists() and time.time() - CACHE.stat().st_mtime < max_age_days * 86400:
        return json.loads(CACHE.read_text(encoding="utf-8"))[:top_n]

    if os.environ.get("FMP_API_KEY"):
        rows = _from_fmp(top_n)
    elif CSV.exists():
        rows = _from_csv()
    else:
        raise RuntimeError("Universo indisponível: define FMP_API_KEY ou cria data/universe.csv "
                           "(symbol,name,exchange,marketCap).")
    universe = _dedupe_top(rows, top_n)
    DATA.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(universe, ensure_ascii=False, indent=1), encoding="utf-8")
    return universe
