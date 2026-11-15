"""0.2 profile_agent: resolve o pedido (ticker, código ou nome) para a cotação PRINCIPAL e viva da empresa,
e monta o contexto de que todos os outros agentes precisam.

Resolução (aprendida com "SSU", que é a Samsung em Frankfurt e também uma empresa americana deslistada):
  1. candidatos diretos (o símbolo tal como escrito; códigos numéricos → .KS/.KQ/.SS/.SZ, .T/.HK)
  2. uma cotação só conta se estiver VIVA (último negócio há ≤ 14 dias) — fornecedores guardam perfis antigos
  3. cotações secundárias (Frankfurt, Estugarda, OTC, Londres IOB…) → cotação principal da mesma empresa
  4. sem candidato direto vivo → pesquisa; correspondência exata do código noutras bolsas (SSU → SSU.F)
  5. várias empresas vivas possíveis → erro com as opções; nenhuma → erro (o fluxo pára aqui, sem gastar LLM)
"""
import importlib.util
import re
from pathlib import Path

from core.data import DataUnavailable, get_router
from core.data.markets import calendar_code, market_of, suffix
from core.util import BENCHMARK, days_between, major_currency

_spec = importlib.util.spec_from_file_location("_profile_schema", Path(__file__).with_name("schema.py"))
_schema = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_schema)
Profile, CrossListing = _schema.Profile, _schema.CrossListing

SYMBOL_RE = re.compile(r"^[A-Z0-9^][A-Z0-9.\-=^]{0,14}$")
SECONDARY_EXCH = {"PNK", "OTC", "OQB", "OQX", "FRA", "BER", "STU", "MUN", "DUS", "HAM", "HAN", "MEX", "BUE", "SGO",
                  "VIE", "NEO", "CXE", "IOB", "AQS", "TLO"}
SECONDARY_SFX = {".F", ".SG", ".BE", ".MU", ".DU", ".HM", ".HA", ".IL", ".XC", ".MX", ".VI", ".BA", ".SN"}
MAX_STALE_DAYS = 14
LEGAL = re.compile(r"\b(inc|corp|corporation|co|ltd|limited|plc|nv|n v|sa|ag|se|holdings?|group|company)\b")


def _candidates(q: str) -> list[str]:
    s = q.strip().upper()
    if re.fullmatch(r"\d{6}", s):              # código coreano ou chinês sem sufixo
        return [f"{s}.KS", f"{s}.KQ", f"{s}.SS", f"{s}.SZ"]
    if re.fullmatch(r"\d{4,5}", s):            # Tóquio (4 dígitos) ou Hong Kong
        return [f"{s}.T", f"{s.zfill(4)}.HK"]
    return [s] if SYMBOL_RE.match(s) else []


def company_key(name: str | None) -> str:
    n = re.sub(r"[^\w\s]", " ", (name or "").lower())
    return re.sub(r"\s+", " ", LEGAL.sub(" ", n)).strip()


def is_secondary(symbol: str, exchange: str | None = None) -> bool:
    return (exchange or "").upper() in SECONDARY_EXCH or suffix(symbol) in SECONDARY_SFX


class Resolver:
    """Resolução com funções injetáveis (testável sem rede)."""

    def __init__(self, r):
        self.r = r
        self._alive: dict[str, tuple[bool, str | None]] = {}

    def profile(self, sym):
        return self.r.get("profile", sym)

    def search(self, q) -> list[dict]:
        try:
            return [h for h in self.r.get("search", q).data if h.get("type") == "EQUITY" and h.get("symbol")]
        except DataUnavailable:
            return []

    def alive(self, sym) -> tuple[bool, str | None]:
        """Viva = barras com preço e volume REAIS nos últimos 14 dias. Alguns fornecedores devolvem barras-fantasma
        para cotações mortas (ex.: Tiingo para SSU: preço 0,000001 e volume 0 todos os dias até hoje)."""
        if sym not in self._alive:
            try:
                bars = self.r.get("eod", sym, days=30).data
            except DataUnavailable:
                bars = []
            real = [b for b in bars if (b.get("c") or 0) > 1e-4 and (b.get("v") is None or b["v"] > 0)]
            last = real[-1]["t"] if real else None
            self._alive[sym] = (last is not None and days_between(last) <= MAX_STALE_DAYS, last)
        return self._alive[sym]

    def primary_listing(self, name: str, exclude: set) -> str | None:
        """Cotação principal viva da empresa: 1.º resultado não secundário da pesquisa pelo nome."""
        key = company_key(name)
        for h in self.search(name):
            if h["symbol"] in exclude or is_secondary(h["symbol"], h.get("exchange")):
                continue
            if company_key(h.get("name")) != key and key not in company_key(h.get("name")):
                continue
            if self.alive(h["symbol"])[0]:
                return h["symbol"]
        return None

    def resolve(self, query: str):
        notes = []
        for sym in _candidates(query):
            try:
                prof = self.profile(sym)
            except DataUnavailable:
                continue
            ok, last = self.alive(sym)
            secondary = is_secondary(sym, prof.data.get("exchange"))
            if ok and not secondary:
                return sym, prof, None
            alt = self.primary_listing(prof.data["name"], {sym})
            stale = f"sem negociação desde {last}" if last else "sem negociação recente"
            if alt:
                why = "cotação secundária" if ok or secondary else stale
                return alt, self.profile(alt), f"{query} → {prof.data['name']} ({alt}); {sym}: {why}"
            if ok:
                return sym, prof, f"{sym} é uma cotação secundária e não encontrei a principal"
            notes.append(f"{sym} ({prof.data['name']}) {stale}")

        q = query.strip().upper()
        hits = self.search(query.strip())
        exact = [h for h in hits if h["symbol"].upper().split(".")[0] == q]
        # código exato noutras bolsas: várias empresas → ambíguo. Pesquisa por nome: a mais relevante (ordem do Yahoo)
        found = self._companies(exact if exact else hits[:6], stop_at_first=not exact)
        if len(found) == 1:
            name, sym = found[0]
            note = f"{query} → {name} ({sym})" + (f"; {notes[0]}" if notes else "")
            return sym, self.profile(sym), note
        if len(found) > 1:
            opts = "; ".join(f"{n} → {s}" for n, s in found[:5])
            raise ValueError(f"'{query}' é ambíguo — escolhe uma: {opts}")
        detail = "; ".join(notes) or "sem resultados"
        raise ValueError(f"não encontrei nenhuma cotação ativa para '{query}' ({detail})")

    def _companies(self, hits: list[dict], stop_at_first: bool) -> list[tuple[str, str]]:
        """(nome, cotação principal viva) por empresa distinta, pela ordem dos resultados."""
        seen, found = set(), []
        for h in hits:
            key = company_key(h.get("name")) or h["symbol"]
            if key in seen:
                continue
            seen.add(key)
            sym = self.primary_listing(h.get("name") or "", set()) or \
                (h["symbol"] if self.alive(h["symbol"])[0] else None)
            if sym:
                found.append((h.get("name"), sym))
                if stop_at_first:
                    break
        return found


LISTING_WORDS = {"gdr", "adr", "ads", "adrs", "sponsored", "unsponsored", "depositary", "receipt", "receipts", "shares",
                 "share", "class", "a", "b", "c", "h", "pref", "preferred", "ordinary", "registered", "reg", "s", "144a"}


def same_company(a: str | None, b: str | None) -> bool:
    """Mesma empresa pelo nome sem a forma jurídica. A pesquisa do Yahoo por "Samsung Electronics" devolvia a
    Nu Holdings (NU) e a da Coupang devolvia a AMD: entravam como "a própria empresa noutra bolsa"."""
    ka, kb = company_key(a).split(), company_key(b).split()
    if not ka or not kb:
        return False
    short, long_ = sorted((ka, kb), key=len)
    # o nome mais longo só pode acrescentar o tipo de título ("… GDR", "… ADR", "… Class A"), não outra empresa
    return long_[:len(short)] == short and set(long_[len(short):]) <= LISTING_WORDS


def _usd(r, amount, currency):
    """amount na moeda PRINCIPAL (libras, não pence)."""
    if amount is None or not currency:
        return None
    currency, _ = major_currency(currency)
    if currency.upper() == "USD":
        return amount
    try:
        rate = r.get("fx", f"USD/{currency.upper()}").data["rate"]
        return amount / rate if rate else None
    except DataUnavailable:
        return None


def run(ticker: str):
    r = get_router()
    res = Resolver(r)
    symbol, prof_res, note = res.resolve(ticker)
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
    for h in res.search(prof["name"]):
        sym = h["symbol"]
        if sym == symbol or is_secondary(sym, h.get("exchange")) or not same_company(h.get("name"), prof["name"]):
            continue
        m = market_of(sym)
        if m in ("OTHER", "INDEX", "FUT", "FX"):
            continue
        cross.append(CrossListing(symbol=sym, exchange=h.get("exchange"), market=m, name=h.get("name")))

    peers = []
    if market == "US":
        try:
            peers = r.get("peers", symbol).data[:10]
        except DataUnavailable:
            pass

    currency = quote.get("currency") or prof.get("currency")
    _, minor_div = major_currency(currency)
    market_cap = prof["market_cap"] / minor_div if prof.get("market_cap") else prof.get("market_cap")
    return Profile(
        query=ticker, symbol=symbol, name=prof["name"], market=market, exchange=prof.get("exchange"),
        calendar=calendar_code(symbol), currency=currency, sector=prof.get("sector"), industry=prof.get("industry"),
        country=prof.get("country"), summary=prof.get("summary"), price=quote.get("price"),
        change_pct=quote.get("change_pct"), quote_ts=quote.get("ts"), market_cap=market_cap,
        market_cap_usd=_usd(r, market_cap, currency), first_trade_date=first, days_listed=days_listed,
        ipo_recente=bool(days_listed is not None and days_listed < 365), history_days=len(bars),
        shares_outstanding=prof.get("shares_outstanding"), float_shares=prof.get("float_shares"),
        benchmark=BENCHMARK.get(market), cross_listings=cross[:8], peers_hint=peers, sources=sources,
        resolution_note=note,
    )
