"""2.9a — dados fundamentais calculados por código."""
from core.data import DataUnavailable, get_router
from core.util import as_dict, major_currency, r2

RF, ERP, TERMINAL_G = 0.04, 0.05, 0.025


def _first(xs):
    return next((x for x in xs or [] if x is not None), None)


def cagr(series: list) -> float | None:
    vals = [v for v in series or [] if v is not None]
    if len(vals) < 2 or vals[-1] <= 0 or vals[0] <= 0:
        return None
    return (vals[0] / vals[-1]) ** (1 / (len(vals) - 1)) - 1


def dcf(fcf0: float, growth: float, wacc: float, net_debt: float, shares: float, years: int = 10) -> dict:
    """2 fases: crescimento `growth` nos anos 1-5, a convergir linearmente para 2,5% até ao ano 10."""
    pv, fcf = 0.0, fcf0
    for t in range(1, years + 1):
        g = growth if t <= 5 else growth + (TERMINAL_G - growth) * (t - 5) / (years - 5)
        fcf *= 1 + g
        pv += fcf / (1 + wacc) ** t
    tv = fcf * (1 + TERMINAL_G) / (wacc - TERMINAL_G)
    pv_tv = tv / (1 + wacc) ** years
    equity = pv + pv_tv - net_debt
    return {"value_per_share": equity / shares, "pv_fcf": pv, "pv_terminal": pv_tv,
            "terminal_share_pct": pv_tv / (pv + pv_tv) * 100}


def share_count(outstanding: float | None, market_cap: float | None, price: float | None) -> float | None:
    """N.º de ações para o valor por ação. `sharesOutstanding` é só UMA classe (GOOGL: 5,9 mil M de classe A em
    12,3 mil M; Samsung sem as preferenciais): market cap ÷ preço dá o total. Se os dois não forem coerentes
    (fora de 0,5×–6× das ações da classe), fica o valor do fornecedor."""
    if market_cap and price and price > 0:
        implied = market_cap / price
        if not outstanding or 0.5 <= implied / outstanding <= 6:
            return implied
    return outstanding


def analyse(fin: dict, price: float | None, fx_to_trading: float = 1.0, comps: dict | None = None,
            minor_div: float = 1.0) -> dict:
    """price: como cotado (em pence se minor_div=100). fx_to_trading: moeda das contas → moeda PRINCIPAL da cotação."""
    inc, bal, cf, rat = fin.get("income", {}), fin.get("balance", {}), fin.get("cashflow", {}), fin.get("ratios", {})
    years = fin.get("fiscal_years") or []
    rev, ni = inc.get("revenue") or [], inc.get("net_income") or []

    def yoy(xs):
        return r2((xs[0] / xs[1] - 1) * 100) if len(xs) > 1 and xs[0] and xs[1] and xs[1] > 0 else None

    def margin(num):
        return [r2(n / d * 100) if n is not None and d else None for n, d in zip(inc.get(num) or [], rev)]

    debt, cash = _first(bal.get("total_debt")), _first(bal.get("cash"))
    ebitda, ebit, intexp = _first(inc.get("ebitda")), _first(inc.get("ebit")), _first(inc.get("interest_expense"))
    net_debt = (debt or 0) - (cash or 0)
    fcf_list = [x for x in cf.get("free_cash_flow") or [] if x is not None]
    mcap = rat.get("market_cap")  # do Yahoo: na moeda principal da cotação, todas as classes
    price_major = price / minor_div if price else None
    shares = share_count((fin.get("shares") or {}).get("outstanding") or _first(bal.get("shares")), mcap, price_major)

    out = {
        "fiscal_years": years, "currency": fin.get("currency"),
        "valuation": {"trailing_pe": r2(rat.get("trailing_pe")), "forward_pe": r2(rat.get("forward_pe")),
                      "price_to_book": r2(rat.get("price_to_book")), "ev_to_ebitda": r2(rat.get("ev_to_ebitda")),
                      "fcf_yield_pct": r2(fcf_list[0] * fx_to_trading / mcap * 100) if fcf_list and mcap else None,
                      "dividend_yield_pct": r2(rat.get("dividend_yield_pct"))},
        "growth": {"revenue_yoy_pct": yoy(rev), "net_income_yoy_pct": yoy(ni),
                   "revenue_cagr_pct": r2(cagr(rev) * 100) if cagr(rev) is not None else None,
                   "years_in_cagr": len([x for x in rev if x is not None])},
        "margins_pct": {"gross": margin("gross_profit"), "operating": margin("operating_income"), "net": margin("net_income")},
        "balance": {"net_debt": r2(net_debt, 0), "net_debt_to_ebitda": r2(net_debt / ebitda) if ebitda else None,
                    "interest_coverage": r2(ebit / abs(intexp)) if ebit and intexp else None,
                    "current_ratio": r2(_first(bal.get("current_assets")) / _first(bal.get("current_liabilities")))
                    if _first(bal.get("current_assets")) and _first(bal.get("current_liabilities")) else None,
                    "roe_pct": r2((rat.get("roe") or 0) * 100) if rat.get("roe") is not None else None},
    }

    growth = cagr(rev)
    growth = 0.03 if growth is None else max(-0.05, min(growth, 0.15))
    beta = rat.get("beta") or 1.0
    wacc = max(0.07, min(RF + beta * ERP, 0.12))
    fcf0 = fcf_list[0] if fcf_list and fcf_list[0] > 0 else (sum(fcf_list) / len(fcf_list) if fcf_list else None)
    if fcf0 and fcf0 > 0 and shares:
        d = dcf(fcf0, growth, wacc, net_debt, shares)
        vps = d["value_per_share"] * fx_to_trading * minor_div  # na unidade em que a ação é cotada
        out["dcf"] = {"value_per_share": r2(vps), "upside_pct": r2((vps / price - 1) * 100) if price else None,
                      "terminal_share_pct": r2(d["terminal_share_pct"]),
                      "assumptions": {"fcf_base": r2(fcf0, 0), "growth_1_5": r2(growth * 100), "terminal_growth": 2.5,
                                      "wacc_pct": r2(wacc * 100), "beta": r2(beta), "rf_pct": RF * 100, "erp_pct": ERP * 100,
                                      "fx_to_trading": r2(fx_to_trading, 6), "shares": r2(shares, 0)}}
    else:
        out["dcf"] = {"value_per_share": None, "note": "FCF negativo ou indisponível: DCF não aplicável"}

    if comps and comps.get("medians"):
        med = comps["medians"]
        v = out["valuation"]
        # um múltiplo negativo (prejuízo, EBITDA negativo) não é "barato": não se compara
        out["vs_peers"] = {k: r2((v[k] / med[k] - 1) * 100) if (v.get(k) or 0) > 0 and (med.get(k) or 0) > 0 else None
                           for k in ("trailing_pe", "forward_pe", "ev_to_ebitda", "price_to_book")}
        out["vs_peers"]["note"] = ("prémio (+) / desconto (−) face à mediana dos peers, em %; "
                                   "múltiplos negativos não se comparam")
    return out


def run(profile, comps=None):
    p = as_dict(profile)
    r = get_router()
    fin = r.get("financials", p["symbol"]).data
    fx = 1.0
    quote_cur, minor_div = major_currency(p.get("currency"))   # Londres: GBp → (GBP, 100)
    fin_cur, _ = major_currency(fin.get("currency"))
    if fin_cur and quote_cur and fin_cur != quote_cur:
        try:
            fx = r.get("fx", f"{fin_cur}/{quote_cur}").data["rate"]
        except DataUnavailable:
            fx = None
    out = analyse(fin, p.get("price"), fx or 1.0, as_dict(comps), minor_div)
    if fx is None:
        out["warning"] = "moeda das contas ≠ moeda de cotação e sem câmbio: DCF por ação pode estar na moeda errada"
    try:
        out["fmp_dcf"] = r.get("dcf", p["symbol"]).data
    except DataUnavailable:
        out["fmp_dcf"] = None
    out["symbol"] = p["symbol"]
    return out
