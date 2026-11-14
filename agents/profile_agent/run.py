"""0.2 profile_agent: contexto de que todos os outros agentes precisam."""
import importlib.util
import re
from datetime import date
from pathlib import Path

from core.data import DataUnavailable, get_router
from core.data.markets import calendar_code, market_of
from core.util import BENCHMARK, days_between

_spec = importlib.util.spec_from_file_location("_profile_schema", Path(__file__).with_name("schema.py"))
_schema = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_schema)
Profile, CrossListing = _schema.Profile, _schema.CrossListing

SYMBOL_RE = re.compile(r"^[A-Z0-9^][A-Z0-9.\-=^]{0,14}$")
SECONDARY_EXCH = {"PNK", "FRA", "BER", "STU", "MUN", "DUS", "HAM", "HAN", "MEX", "BUE", "SGO", "VIE", "NEO"}


def _candidates(q: str) -> list[str]:
    s = q.strip().upper()
    if re.fullmatch(r"\d{6}", s):              # código coreano ou chinês sem sufixo
        return [f"{s}.KS", f"{s}.KQ", f"{s}.SS", f"{s}.SZ"]
    if re.fullmatch(r"\d{4,5}", s):            # Tóquio (4 dígitos) ou Hong Kong
        return [f"{s}.T", f"{s.zfill(4)}.HK"]
    return [s] if SYMBOL_RE.match(s) else []


def resolve(r, query: str):
    tried = []
    for sym in _candidates(query):
        try:
            return sym, r.get("profile", sym)
        except DataUnavailable as e:
            tried.append(f"{sym}: {e}")
    hits = [h for h in r.get("search", query.strip()).data if h.get("type") == "EQUITY"
            and h.get("exchange") not in SECONDARY_EXCH]
    for h in hits[:5]:
        try:
            return h["symbol"], r.get("profile", h["symbol"])
        except DataUnavailable as e:
            tried.append(f"{h['symbol']}: {e}")
    raise ValueError(f"não consegui resolver '{query}' ({'; '.join(tried) or 'sem resultados'})")


def _usd(r, amount, currency):
    if amount is None or not currency:
        return None
    if currency in ("GBp", "GBX"):  # Londres cota em pence
        amount, currency = amount / 100, "GBP"
    if currency.upper() == "USD":
        return amount
    try:
        rate = r.get("fx", f"USD/{currency.upper()}").data["rate"]
        return amount / rate if rate else None
    except DataUnavailable:
        return None


def run(ticker: str):
    r = get_router()
    symbol, prof_res = resolve(r, ticker)
    prof = prof_res.data
    market = market_of(symbol)
    sources = {"profile": prof_res.provider}

    quote = {}
    try:
        q = r.get("quote", symbol)
        quote, sources["quote"] = q.data, q.provider
    except DataUnavailable:
        pass

    bars = []
    try:
        e = r.get("eod", symbol, days=400)
        bars, sources["eod"] = e.data, e.provider
    except DataUnavailable:
        pass

    first = prof.get("first_trade_date") or (bars[0]["t"] if bars and len(bars) < 240 else None)
    days_listed = days_between(first) if first else None

    cross = []
    try:
        for h in r.get("search", prof["name"]).data:
            sym = h.get("symbol")
            if not sym or sym == symbol or h.get("type") != "EQUITY" or h.get("exchange") in SECONDARY_EXCH:
                continue
            m = market_of(sym)
            if m in ("OTHER", "INDEX", "FUT", "FX"):
                continue
            cross.append(CrossListing(symbol=sym, exchange=h.get("exchange"), market=m, name=h.get("name")))
    except DataUnavailable:
        pass

    peers = []
    if market == "US":
        try:
            peers = r.get("peers", symbol).data[:10]
        except DataUnavailable:
            pass

    currency = quote.get("currency") or prof.get("currency")
    return Profile(
        query=ticker, symbol=symbol, name=prof["name"], market=market, exchange=prof.get("exchange"),
        calendar=calendar_code(symbol), currency=currency, sector=prof.get("sector"), industry=prof.get("industry"),
        country=prof.get("country"), summary=prof.get("summary"), price=quote.get("price"),
        change_pct=quote.get("change_pct"), quote_ts=quote.get("ts"), market_cap=prof.get("market_cap"),
        market_cap_usd=_usd(r, prof.get("market_cap"), currency), first_trade_date=first, days_listed=days_listed,
        ipo_recente=bool(days_listed is not None and days_listed < 365), history_days=len(bars),
        shares_outstanding=prof.get("shares_outstanding"), float_shares=prof.get("float_shares"),
        benchmark=BENCHMARK.get(market), cross_listings=cross[:8], peers_hint=peers, sources=sources,
    )
