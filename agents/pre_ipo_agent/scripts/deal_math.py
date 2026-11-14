"""Matemática da oferta de um IPO (nunca de cabeça).

Uso: python scripts/deal_math.py --price-low 70 --price-high 78 --offered 825000000 --post-shares 9500000000
                                  [--primary 600000000] [--greenshoe-pct 15] [--revenue 5e9] [--ebitda 1e9]
Saída: JSON com valorização implícita (baixa/alta), free float, valor da oferta, múltiplos implícitos.
"""
import argparse
import json


def compute(price_low, price_high, offered, post_shares, primary=None, greenshoe_pct=0.0, revenue=None, ebitda=None):
    out = {"inputs": {"price_low": price_low, "price_high": price_high, "offered": offered, "post_shares": post_shares,
                      "primary": primary, "greenshoe_pct": greenshoe_pct}}
    for tag, px in (("low", price_low), ("high", price_high)):
        cap = px * post_shares
        out[f"implied_valuation_{tag}"] = round(cap, 2)
        out[f"offer_value_{tag}"] = round(px * offered * (1 + greenshoe_pct / 100), 2)
        if revenue:
            out[f"implied_ev_sales_{tag}"] = round(cap / revenue, 2)
        if ebitda and ebitda > 0:
            out[f"implied_ev_ebitda_{tag}"] = round(cap / ebitda, 2)
    out["free_float_pct"] = round(offered * (1 + greenshoe_pct / 100) / post_shares * 100, 2)
    if primary is not None:
        out["primary_pct_of_offer"] = round(primary / offered * 100, 1) if offered else None
        out["secondary_shares"] = offered - primary
    out["note"] = "EV aproximado pela market cap (sem dívida líquida); confirmar dívida/caixa no prospeto"
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--price-low", type=float, required=True)
    p.add_argument("--price-high", type=float, required=True)
    p.add_argument("--offered", type=float, required=True, help="ações oferecidas (sem greenshoe)")
    p.add_argument("--post-shares", type=float, required=True, help="ações em circulação depois da oferta")
    p.add_argument("--primary", type=float)
    p.add_argument("--greenshoe-pct", type=float, default=0.0)
    p.add_argument("--revenue", type=float)
    p.add_argument("--ebitda", type=float)
    a = p.parse_args()
    print(json.dumps(compute(a.price_low, a.price_high, a.offered, a.post_shares, a.primary, a.greenshoe_pct,
                             a.revenue, a.ebitda), ensure_ascii=False))
