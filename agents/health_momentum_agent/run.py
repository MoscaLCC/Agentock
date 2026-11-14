"""2.7 — saúde, força e momentum. Cálculos próprios (todos os mercados); nos EUA compara com os scores do FMP."""
from core.data import DataUnavailable, get_router
from core.util import as_dict, r2


def _g(block, key, i):
    vals = (block or {}).get(key) or []
    return vals[i] if i < len(vals) else None


def _div(a, b):
    return a / b if a is not None and b not in (None, 0) else None


def piotroski(fin: dict) -> dict:
    inc, bal, cf = fin.get("income"), fin.get("balance"), fin.get("cashflow")
    ni0, ni1 = _g(inc, "net_income", 0), _g(inc, "net_income", 1)
    ta0, ta1 = _g(bal, "total_assets", 0), _g(bal, "total_assets", 1)
    cfo0 = _g(cf, "operating_cash_flow", 0)
    roa0, roa1 = _div(ni0, ta0), _div(ni1, ta1)
    lev0, lev1 = _div(_g(bal, "long_term_debt", 0), ta0), _div(_g(bal, "long_term_debt", 1), ta1)
    cr0 = _div(_g(bal, "current_assets", 0), _g(bal, "current_liabilities", 0))
    cr1 = _div(_g(bal, "current_assets", 1), _g(bal, "current_liabilities", 1))
    sh0, sh1 = _g(bal, "shares", 0), _g(bal, "shares", 1)
    gm0 = _div(_g(inc, "gross_profit", 0), _g(inc, "revenue", 0))
    gm1 = _div(_g(inc, "gross_profit", 1), _g(inc, "revenue", 1))
    at0, at1 = _div(_g(inc, "revenue", 0), ta0), _div(_g(inc, "revenue", 1), ta1)
    tests = {
        "roa_positivo": None if roa0 is None else roa0 > 0,
        "cfo_positivo": None if cfo0 is None else cfo0 > 0,
        "roa_a_subir": None if None in (roa0, roa1) else roa0 > roa1,
        "cfo_maior_que_lucro": None if None in (cfo0, ni0) else cfo0 > ni0,
        "alavancagem_a_descer": None if None in (lev0, lev1) else lev0 <= lev1,
        "liquidez_a_subir": None if None in (cr0, cr1) else cr0 > cr1,
        "sem_diluicao": None if None in (sh0, sh1) else sh0 <= sh1,
        "margem_bruta_a_subir": None if None in (gm0, gm1) else gm0 > gm1,
        "rotacao_ativos_a_subir": None if None in (at0, at1) else at0 > at1,
    }
    avail = [v for v in tests.values() if v is not None]
    pts = sum(avail)
    return {"points": pts, "available": len(avail), "score_9": r2(pts / len(avail) * 9, 1) if avail else None,
            "tests": tests}


def altman(fin: dict, market_cap: float | None, sector: str | None) -> dict:
    inc, bal = fin.get("income"), fin.get("balance")
    ta, tl = _g(bal, "total_assets", 0), _g(bal, "total_liabilities", 0)
    wc = _g(bal, "working_capital", 0)
    if wc is None and _g(bal, "current_assets", 0) is not None and _g(bal, "current_liabilities", 0) is not None:
        wc = _g(bal, "current_assets", 0) - _g(bal, "current_liabilities", 0)
    parts = [_div(wc, ta), _div(_g(bal, "retained_earnings", 0), ta), _div(_g(inc, "ebit", 0), ta),
             _div(market_cap, tl), _div(_g(inc, "revenue", 0), ta)]
    if any(p is None for p in parts):
        return {"z": None, "zone": None, "note": "dados insuficientes"}
    z = 1.2 * parts[0] + 1.4 * parts[1] + 3.3 * parts[2] + 0.6 * parts[3] + 1.0 * parts[4]
    zone = "segura" if z > 2.99 else "cinzenta" if z >= 1.81 else "risco"
    note = "pouco significativo em bancos/seguradoras" if sector and "Financial" in sector else None
    return {"z": r2(z), "zone": zone, "note": note}


def _band(x, cuts, scores, default=None):
    if x is None:
        return default
    for c, s in zip(cuts, scores):
        if x >= c:
            return s
    return scores[-1]


def scores(fin: dict, pio: dict, alt: dict, mom: dict) -> dict:
    r = fin.get("ratios") or {}
    de = r.get("debt_to_equity")
    de = de / 100 if de and de > 10 else de  # o yfinance devolve em %
    lev = None if de is None else 100 if de < 0.5 else 70 if de < 1 else 40 if de < 2 else 15
    zone = {"segura": 100, "cinzenta": 60, "risco": 20}.get(alt.get("zone"))
    pio_s = pio["score_9"] / 9 * 100 if pio.get("score_9") is not None else None
    parts = [(pio_s, 0.5), (zone, 0.3), (lev, 0.2)]
    health = sum(v * w for v, w in parts if v is not None) / sum(w for v, w in parts if v is not None) \
        if any(v is not None for v, _ in parts) else None
    roe = r.get("roe")
    om = r.get("operating_margin")
    rev = (fin.get("income") or {}).get("revenue") or []
    g = _div(rev[0] - rev[1], abs(rev[1])) if len(rev) > 1 and None not in rev[:2] else None
    sp = [(_band(roe and roe * 100, [20, 10, 0], [100, 70, 40, 10]), 0.4),
          (_band(om and om * 100, [25, 10, 0], [100, 70, 40, 10]), 0.4),
          (_band(g and g * 100, [15, 5, 0], [100, 70, 50, 20]), 0.2)]
    strength = sum(v * w for v, w in sp if v is not None) / sum(w for v, w in sp if v is not None) \
        if any(v is not None for v, _ in sp) else None
    rel = mom.get("relative_pp") or {}
    m = None
    if rel.get("3m") is not None:
        m = 50 + 0.8 * (rel.get("3m") or 0) + 0.5 * (rel.get("6m") or 0) + 0.3 * (rel.get("12m") or 0)
        m = max(0, min(100, m))
    return {"health_score": r2(health, 0), "strength_score": r2(strength, 0), "momentum_score": r2(m, 0),
            "formulas": {"health": "50% Piotroski + 30% zona Altman + 20% dívida/capital",
                         "strength": "40% ROE + 40% margem operacional + 20% crescimento da receita",
                         "momentum": "50 + 0,8×rel3m + 0,5×rel6m + 0,3×rel12m (pontos percentuais vs índice)"}}


def momentum(bars: list[dict], bench: list[dict]) -> dict:
    def ret(b, n):
        c = [x["c"] for x in b if x.get("c")]
        return (c[-1] / c[-n - 1] - 1) * 100 if len(c) > n else None
    out = {"stock_pct": {}, "benchmark_pct": {}, "relative_pp": {}}
    for k, n in (("1m", 21), ("3m", 63), ("6m", 126), ("12m", 252)):
        s, b = ret(bars, n), ret(bench, n)
        out["stock_pct"][k], out["benchmark_pct"][k] = r2(s), r2(b)
        out["relative_pp"][k] = r2(s - b) if s is not None and b is not None else None
    return out


def run(profile):
    p = as_dict(profile)
    r = get_router()
    sym = p["symbol"]
    fin = r.get("financials", sym).data
    try:
        bars = r.get("eod", sym, days=400).data
    except DataUnavailable:
        bars = []
    bench = []
    if p.get("benchmark"):
        try:
            bench = r.get("eod", p["benchmark"], days=400).data
        except DataUnavailable:
            pass
    mcap = p.get("market_cap")
    if fin.get("currency") and p.get("currency") and fin["currency"] != p["currency"] and mcap:
        try:  # market cap na moeda de reporte (ex.: ADR em USD, contas em CNY)
            mcap = mcap * r.get("fx", f"{p['currency'].upper()}/{fin['currency'].upper()}").data["rate"]
        except DataUnavailable:
            mcap = None
    pio, alt, mom = piotroski(fin), altman(fin, mcap, p.get("sector")), momentum(bars, bench)
    out = {"symbol": sym, "piotroski": pio, "altman": alt, "momentum": mom, **scores(fin, pio, alt, mom),
           "benchmark": p.get("benchmark"), "fiscal_years": fin.get("fiscal_years")}
    try:
        out["fmp_scores"] = r.get("scores", sym).data  # validação cruzada (EUA)
    except DataUnavailable:
        out["fmp_scores"] = None
    return out
