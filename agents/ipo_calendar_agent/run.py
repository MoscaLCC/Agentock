"""I.1 — calendário de IPOs normalizado, filtrado e com alerta dos novos."""
import re

from core import db, messages
from core.data import DataUnavailable, get_router
from core.notify import default_notifier
from core.util import as_dict

SPAC = re.compile(r"acquisition|blank\s*check|\bspac\b|merger\s+corp|capital\s+corp\.?\s+[ivx]+\b", re.I)


def norm_name(n: str) -> str:
    n = re.sub(r"[,.]|\b(inc|corp|corporation|ltd|limited|plc|pbc|co|holdings?|group|class [a-z])\b", " ", (n or "").lower())
    return re.sub(r"\s+", " ", n).strip()


def price_mid(pr) -> float | None:
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(pr or ""))]
    nums = [x for x in nums if x > 0]
    return sum(nums[:2]) / len(nums[:2]) if nums else None


def normalize(items: list[dict], min_value_usd: float, include_spacs: bool) -> dict:
    seen, keep, spacs, small = {}, [], 0, 0
    for it in items:
        key = (it.get("symbol") or "").upper() or norm_name(it.get("name"))
        if not key:
            continue
        cur = seen.get(key)
        if cur:  # junta informação das várias fontes
            for k, v in it.items():
                if cur.get(k) in (None, "", 0) and v not in (None, ""):
                    cur[k] = v
            continue
        seen[key] = dict(it)
    for it in seen.values():
        it["is_spac"] = bool(SPAC.search(it.get("name") or ""))
        value = it.get("value")
        if not value and it.get("shares") and price_mid(it.get("price_range")):
            value = it["shares"] * price_mid(it["price_range"])
        it["value_usd"] = float(value) if value else None
        if it["is_spac"] and not include_spacs:
            spacs += 1
            continue
        if it["value_usd"] is not None and it["value_usd"] < min_value_usd:
            small += 1
            continue
        it["size_known"] = it["value_usd"] is not None
        keep.append(it)
    keep.sort(key=lambda x: (x.get("date") or "9999", -(x.get("value_usd") or 0)))
    return {"ipos": keep, "excluded": {"spacs": spacs, "below_threshold": small}}


def run(days=30, min_value_usd=500_000_000, include_spacs=False, notify=True, web=None):
    r = get_router()
    items, src = [], None
    try:
        res = r.get("ipo_calendar", None, days=days)
        items, src = list(res.data), res.provider
    except DataUnavailable:
        pass
    web = as_dict(web)
    if web and web.get("ipos"):
        items += [{**i, "provider": "web"} for i in web["ipos"]]
    out = normalize(items, min_value_usd, include_spacs)
    out.update({"days": days, "min_value_usd": min_value_usd, "sources": src})
    conn = db.connect()
    new = []
    for it in out["ipos"]:
        key = f"ipo:{(it.get('symbol') or norm_name(it.get('name'))).upper()}"
        if not db.was_seen(conn, key):
            new.append(it)
            db.mark_seen(conn, key, "ipo", it)
    out["new"] = new
    if notify and new:
        out["alert_sent"] = default_notifier().send(messages.new_ipos(new), html=True)
    return out
