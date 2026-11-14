"""2.17 — preços-alvo e potencial."""
from datetime import date, timedelta

from core.data import DataUnavailable, get_router
from core.util import as_dict, r2


def summarize(pt: dict | None, price: float | None, upgrades: list | None, today: date | None = None) -> dict:
    today = today or date.today()
    pt = pt or {}
    price = price or pt.get("current")

    def up(x):
        return r2((x / price - 1) * 100) if x and price else None

    mean, med, lo, hi = pt.get("mean"), pt.get("median"), pt.get("low"), pt.get("high")
    cutoff = (today - timedelta(days=90)).isoformat()
    firm = [{"date": u["date"], "firm": u.get("firm"), "target": u["price_target"],
             "prior": u.get("prior_price_target"), "rating": u.get("to_grade")}
            for u in (upgrades or []) if u.get("price_target") and (u.get("date") or "") >= cutoff]
    avg_recent = sum(f["target"] for f in firm) / len(firm) if firm else None
    raised = sum(1 for f in firm if f["prior"] and f["target"] > f["prior"])
    cut = sum(1 for f in firm if f["prior"] and f["target"] < f["prior"])
    return {
        "price": r2(price), "mean": r2(mean), "median": r2(med), "low": r2(lo), "high": r2(hi),
        "upside_mean_pct": up(mean), "upside_median_pct": up(med), "upside_low_pct": up(lo), "upside_high_pct": up(hi),
        "dispersion_pct": r2((hi - lo) / mean * 100) if hi and lo and mean else None,
        "recent_firm_targets": firm[:10], "recent_avg_target": r2(avg_recent), "upside_recent_avg_pct": up(avg_recent),
        "raised_90d": raised, "cut_90d": cut,
    }


def run(profile):
    p = as_dict(profile)
    r = get_router()
    pt = upgrades = None
    src = {}
    try:
        res = r.get("price_targets", p["symbol"])
        pt, src["targets"] = res.data, res.provider
    except DataUnavailable:
        pass
    try:
        res = r.get("upgrades", p["symbol"])
        upgrades, src["upgrades"] = res.data, res.provider
    except DataUnavailable:
        pass
    out = summarize(pt, p.get("price"), upgrades)
    out.update({"symbol": p["symbol"], "currency": p.get("currency"), "sources": src, "available": pt is not None})
    return out
