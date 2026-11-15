"""2.12b — comparáveis. Números por código (router); o LLM só escolheu os peers."""
import statistics

from core.data import DataUnavailable, get_router
from core.util import as_dict, major_currency, r2

METRICS = ("trailing_pe", "forward_pe", "ev_to_ebitda", "price_to_book", "gross_margin", "operating_margin",
           "revenue_growth", "roe")


MULTIPLES = ("trailing_pe", "forward_pe", "ev_to_ebitda", "price_to_book")  # negativos não entram nas medianas


def row(r, symbol: str) -> dict | None:
    try:
        prof = r.get("profile", symbol).data
        fin = r.get("financials", symbol).data
    except DataUnavailable:
        return None
    rat = fin.get("ratios") or {}
    out = {"symbol": symbol, "name": prof.get("name"), "currency": prof.get("currency"),
           "market_cap": prof.get("market_cap")}
    for m in METRICS:
        v = rat.get(m)
        out[m] = r2(v * 100) if v is not None and m in ("gross_margin", "operating_margin", "revenue_growth", "roe") else r2(v)
    try:
        bars = r.get("eod", symbol, days=400).data
        c = [b["c"] for b in bars if b.get("c")]
        out["ret_3m_pct"] = r2((c[-1] / c[-64] - 1) * 100) if len(c) > 64 else None
        out["ret_12m_pct"] = r2((c[-1] / c[-253] - 1) * 100) if len(c) > 253 else None
    except DataUnavailable:
        out["ret_3m_pct"] = out["ret_12m_pct"] = None
    cur, div = major_currency(out["currency"] or "USD")
    mc = out["market_cap"] / div if out["market_cap"] else out["market_cap"]   # fast_info: em pence em Londres
    out["market_cap"] = mc
    try:
        rate = 1.0 if cur == "USD" else r.get("fx", f"USD/{cur}").data["rate"]
        out["market_cap_usd"] = r2(mc / rate, 0) if mc and rate else None
    except DataUnavailable:
        out["market_cap_usd"] = None
    return out


def medians(rows: list[dict]) -> dict:
    out = {}
    for m in METRICS + ("ret_3m_pct", "ret_12m_pct"):
        vals = [x[m] for x in rows if x.get(m) is not None and (m not in MULTIPLES or x[m] > 0)]
        out[m] = r2(statistics.median(vals)) if vals else None
    return out


def relative(target: dict, med: dict) -> dict:
    return {m: r2(target[m] - med[m]) if target.get(m) is not None and med.get(m) is not None else None
            for m in METRICS + ("ret_3m_pct", "ret_12m_pct")}


def run(profile, competitors):
    p, comp = as_dict(profile), as_dict(competitors)
    r = get_router()
    target = row(r, p["symbol"])
    peers, dropped = [], []
    for peer in comp.get("peers") or []:
        x = row(r, peer["symbol"])
        if x is None:
            dropped.append({"symbol": peer["symbol"], "reason": "sem dados no router"})
            continue
        if target and target.get("market_cap_usd") and x.get("market_cap_usd"):
            ratio = x["market_cap_usd"] / target["market_cap_usd"]
            x["size_ratio"] = r2(ratio, 3)
            if ratio < 1 / 50 or ratio > 50:
                x["flag"] = "dimensão muito diferente"
        x["overlap"] = peer.get("overlap")
        peers.append(x)
    med = medians(peers)
    return {"symbol": p["symbol"], "target": target, "peers": peers, "dropped": dropped, "medians": med,
            "target_minus_median": relative(target, med) if target else None,
            "note": "margens, crescimento, ROE e retornos em %; diferenças em pontos (target − mediana)"}
