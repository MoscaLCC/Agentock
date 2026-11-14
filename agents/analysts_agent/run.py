"""2.16 — consenso: score médio −2 (venda forte) … +2 (compra forte), tendência face a 3 meses, upgrades/downgrades.

Fora dos EUA não há alterações por casa nas fontes grátis; essas notícias chegam pelos agentes de notícias
(categoria "analyst") e entram no sentimento (2.10).
"""
from datetime import date, timedelta

from core.data import DataUnavailable, get_router
from core.util import as_dict, r2

W = {"strong_buy": 2, "buy": 1, "hold": 0, "sell": -1, "strong_sell": -2}


def score(rec: dict | None):
    if not rec:
        return None, 0
    n = sum((rec.get(k) or 0) for k in W)
    if not n:
        return None, 0
    return sum((rec.get(k) or 0) * w for k, w in W.items()) / n, n


def label(s):
    if s is None:
        return None
    return ("compra forte" if s >= 1.5 else "compra" if s >= 0.5 else "neutro" if s > -0.5
            else "venda" if s > -1.5 else "venda forte")


def summarize(recs: dict | None, upgrades: list | None, today: date | None = None) -> dict:
    today = today or date.today()
    s, n = score(recs)
    hist = (recs or {}).get("history") or []
    old = score(hist[-1])[0] if len(hist) > 1 else None
    cutoff = (today - timedelta(days=90)).isoformat()
    recent = [u for u in (upgrades or []) if (u.get("date") or "") >= cutoff]
    acts = [str(u.get("action") or "").lower() for u in recent]
    up = sum(a in ("up", "upgrade") for a in acts)
    down = sum(a in ("down", "downgrade") for a in acts)
    init = sum(a in ("init", "initialise", "initiated", "initialize") for a in acts)
    return {
        "counts": {k: (recs or {}).get(k) for k in W}, "n_analysts": n,
        "consensus_score": r2(s), "consensus_label": label(s),
        "score_3m_ago": r2(old), "trend": None if old is None or s is None else r2(s - old),
        "changes_90d": {"up": up, "down": down, "init": init, "net": up - down, "total": len(recent)},
        "recent_changes": recent[:8],
    }


def run(profile):
    p = as_dict(profile)
    r = get_router()
    recs = upgrades = None
    src = {}
    try:
        res = r.get("analyst_recs", p["symbol"])
        recs, src["recs"] = res.data, res.provider
    except DataUnavailable:
        pass
    try:
        res = r.get("upgrades", p["symbol"])
        upgrades, src["upgrades"] = res.data, res.provider
    except DataUnavailable:
        pass
    out = summarize(recs, upgrades)
    out.update({"symbol": p["symbol"], "sources": src, "available": recs is not None})
    return out
