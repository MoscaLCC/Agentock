"""2.18a — intervalos estatísticos. Modelo simples e explícito: lognormal com MEDIANA no preço atual (sem
tendência) e volatilidade de 1 ano. Antes era a média que ficava no preço: com volatilidade alta a mediana a
12 meses caía muito (Samsung, 77%: −25,7%) e era lida como cenário central pessimista."""
import math

from core.data import DataUnavailable, get_router
from core.util import as_dict, r2

HORIZONS = {"1m": 21, "3m": 63, "12m": 252}
Z = {"p10": -1.2816, "p25": -0.6745, "p50": 0.0, "p75": 0.6745, "p90": 1.2816}


def ranges(price: float, closes: list[float]) -> dict:
    rets = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a and b and a > 0 and b > 0][-252:]
    if len(rets) < 20 or not price:
        return {"available": False, "reason": "histórico insuficiente"}
    mu = sum(rets) / len(rets)
    sd = math.sqrt(sum((x - mu) ** 2 for x in rets) / (len(rets) - 1))
    out = {"available": True, "daily_vol_pct": r2(sd * 100, 3), "annual_vol_pct": r2(sd * math.sqrt(252) * 100),
           "observations": len(rets), "horizons": {},
           "model": "lognormal sem tendência (p50 = preço atual), volatilidade dos últimos 252 dias"}
    for h, n in HORIZONS.items():
        s = sd * math.sqrt(n)
        out["horizons"][h] = {q: sig(price * math.exp(z * s)) for q, z in Z.items()}
    return out


def sig(x: float, digits: int = 5) -> float:
    """Arredonda a algarismos significativos (2 casas zeravam ações de cêntimos: SSU a 0,09 USD → 0,0)."""
    if not x:
        return 0.0
    return round(x, max(2, digits - 1 - int(math.floor(math.log10(abs(x))))))


def run(profile, price_targets=None, fundamental_data=None):
    p = as_dict(profile)
    pt, fd = as_dict(price_targets) or {}, as_dict(fundamental_data) or {}
    price = p.get("price")
    try:
        closes = [b["c"] for b in get_router().get("eod", p["symbol"], days=400).data if b.get("c")]
    except DataUnavailable:
        closes = []
    out = ranges(price or (closes[-1] if closes else None), closes)
    out["price"] = price
    out["anchors"] = {
        "analyst_mean": pt.get("mean"), "analyst_median": pt.get("median"), "analyst_low": pt.get("low"),
        "analyst_high": pt.get("high"), "dcf_own": (fd.get("dcf") or {}).get("value_per_share"),
        "dcf_fmp": (fd.get("fmp_dcf") or {}).get("dcf"),
    }
    out["symbol"] = p["symbol"]
    return out
