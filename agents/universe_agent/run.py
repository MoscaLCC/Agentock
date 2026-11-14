"""0.1 — universo das maiores empresas do mundo.

1. screener do yfinance por região (market cap na moeda local)
2. conversão para USD (router fx; GBp/ILA/ZAc em centésimos)
3. só ações (EQUITY), fora das bolsas secundárias
4. uma cotação por empresa: a de MAIOR LIQUIDEZ (valor médio negociado/dia em USD = volume médio 3m × preço);
   desempate pela pontuação de moeda/sufixo. Evita escolher a Apple na Xetra (APC.DE) ou a ASML em Frankfurt
   (ASME.DE) — a pontuação por moeda sozinha falhava em multinacionais que reportam em USD (Shell, HSBC).
5. validação contra megacaps de referência (config/universe.yaml)
"""
import json
import re
import time
from pathlib import Path

import yaml

from core.data import DataUnavailable, get_router
from core.data.markets import suffix

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "universe.json"
CFG = ROOT / "config" / "universe.yaml"
CENTS = {"GBp": "GBP", "GBX": "GBP", "ILA": "ILS", "ZAc": "ZAR"}
SUFFIXES = r"\b(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|ag|sa|s\.a|nv|n\.v|se|spa|asa|ab|oyj|as|a/s|" \
           r"holdings?|group|bhd|tbk|class [a-z]|ordinary shares?|common stock|the)\b"


def norm_name(n: str) -> str:
    n = re.sub(r"[^\w\s/.]", " ", (n or "").lower())
    n = re.sub(SUFFIXES, " ", n)
    return re.sub(r"[\s.]+", " ", n).strip()


def score(q: dict, cfg: dict) -> int:
    s = 0
    if q.get("currency") and q.get("financial_currency") and \
            CENTS.get(q["currency"], q["currency"]) == q["financial_currency"]:
        s += 2
    if suffix(q["symbol"]) in (cfg["home_suffix"].get(q.get("currency")) or []):
        s += 1
    if q.get("exchange") in cfg["secondary_exchanges"]:
        s -= 3
    return s


def select(quotes: list[dict], cfg: dict, top_n: int) -> list[dict]:
    by_company: dict[str, dict] = {}
    excl = [re.compile(p) for p in cfg.get("exclude_patterns", [])]
    for q in quotes:
        if q.get("quote_type") != "EQUITY" or not q.get("market_cap_usd") or q.get("exchange") in cfg["secondary_exchanges"]:
            continue
        if any(rx.match(q["symbol"]) for rx in excl):
            continue
        q["score"] = score(q, cfg)
        key = norm_name(q.get("name")) or q["symbol"]
        cur = by_company.get(key)
        rank = (q.get("traded_value_usd") or 0, q["score"], q["market_cap_usd"])
        if cur is None or rank > (cur.get("traded_value_usd") or 0, cur["score"], cur["market_cap_usd"]):
            by_company[key] = q
    return sorted(by_company.values(), key=lambda x: -x["market_cap_usd"])[:top_n]


def validate(universe: list[dict], reference: list[str]) -> list[str]:
    have = {u["symbol"] for u in universe}
    return [ref for ref in reference if not any(alt in have for alt in ref.split("|"))]


def _screen(region: str, size: int) -> list[dict]:
    import yfinance as yf
    from yfinance import EquityQuery
    q = EquityQuery("and", [EquityQuery("eq", ["region", region]), EquityQuery("gt", ["intradaymarketcap", 1e8])])
    rows, offset = [], 0
    while offset < size:  # páginas de 250
        res = yf.screen(q, sortField="intradaymarketcap", sortAsc=False, size=min(250, size - offset), offset=offset)
        page = res.get("quotes", [])
        rows += page
        if len(page) < min(250, size - offset):
            break
        offset += len(page)
    return [{"symbol": x["symbol"], "name": x.get("longName") or x.get("shortName"), "exchange": x.get("exchange"),
             "currency": x.get("currency"), "financial_currency": x.get("financialCurrency"),
             "market_cap": x.get("marketCap"), "quote_type": x.get("quoteType"), "region": region,
             "price": x.get("regularMarketPrice"), "avg_volume": x.get("averageDailyVolume3Month")}
            for x in rows if x.get("symbol")]


def _inject_missing(r, universe: list[dict], cfg: dict) -> list[str]:
    """Megacaps de referência que o screener não devolveu: acrescenta-as via router."""
    injected = []
    for ref in validate(universe, cfg["reference"]):
        sym = ref.split("|")[0]
        try:
            prof = r.get("profile", sym).data
            quote = r.get("quote", sym).data
        except DataUnavailable:
            continue
        q = {"symbol": sym, "name": prof.get("name"), "exchange": prof.get("exchange"),
             "currency": quote.get("currency") or prof.get("currency"), "financial_currency": None,
             "market_cap": prof.get("market_cap"), "quote_type": "EQUITY", "region": "injected"}
        _to_usd(r, [q])
        if q.get("market_cap_usd"):
            q["score"] = 0
            universe.append(q)
            injected.append(sym)
    return injected


def _to_usd(r, quotes: list[dict]) -> None:
    rates: dict[str, float | None] = {"USD": 1.0}
    for q in quotes:
        cur = q.get("currency")
        if not cur or not q.get("market_cap"):
            q["market_cap_usd"] = None
            continue
        base = CENTS.get(cur, cur).upper()
        factor = 100 if cur in CENTS else 1
        if base not in rates:
            try:
                rates[base] = r.get("fx", f"USD/{base}").data["rate"]
            except DataUnavailable:
                rates[base] = None
        rate = rates[base]
        q["market_cap_usd"] = q["market_cap"] / factor / rate if rate else None
        if rate and q.get("price") and q.get("avg_volume"):
            q["traded_value_usd"] = q["price"] * q["avg_volume"] / factor / rate


def run(top_n=500, refresh=False, max_age_days=1):
    if not refresh and CACHE.exists() and time.time() - CACHE.stat().st_mtime < max_age_days * 86400:
        cached = json.loads(CACHE.read_text(encoding="utf-8"))
        if cached.get("top_n", 0) >= top_n:
            return {**cached, "universe": cached["universe"][:top_n], "cached": True}
    cfg = yaml.safe_load(CFG.read_text(encoding="utf-8"))
    r = get_router()
    quotes, errors = [], {}
    for region, size in cfg["regions"].items():
        try:
            quotes += _screen(region, size)
        except Exception as e:  # uma região falhada não pára o universo
            errors[region] = f"{type(e).__name__}: {str(e)[:120]}"
    _to_usd(r, quotes)
    universe = select(quotes, cfg, top_n)
    big = top_n >= 200  # a referência (megacaps) só faz sentido num universo grande
    injected = _inject_missing(r, universe, cfg) if big else []
    universe = sorted(universe, key=lambda x: -x["market_cap_usd"])[:top_n]
    injected = [s for s in injected if s in {u["symbol"] for u in universe}]
    for i, u in enumerate(universe, 1):
        u["rank"] = i
    out = {"generated": time.strftime("%Y-%m-%d %H:%M"), "top_n": top_n, "candidates": len(quotes),
           "universe": universe, "injected": injected,
           "missing_reference": validate(universe, cfg["reference"]) if big else None,
           "region_errors": errors}
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out
