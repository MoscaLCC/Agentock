"""I.3 — ciclo pós-IPO. Lock-up: nos EUA lê o prazo no 424B4; fora dos EUA usa a convenção do mercado (não confirmada)."""
from datetime import date, timedelta

from core import db
from core.data import DataUnavailable, get_router
from core.notify import DISCLAIMER, default_notifier
from core.util import as_dict, r2

TYPICAL_LOCKUP = {"US": 180, "HK": 180, "KR": 180, "JP": 180, "EU": 180, "CN": 365}


def events(debut: date, market: str, lockup_days: int, lockup_confirmed: bool) -> list[dict]:
    ev = [{"date": debut.isoformat(), "type": "ipo_debut", "label": "Estreia em bolsa", "confirmed": True}]
    if market == "US":
        ev.append({"date": (debut + timedelta(days=25)).isoformat(), "type": "quiet_period_end",
                   "label": "Fim do período de silêncio (25 dias): início da cobertura dos bancos do IPO", "confirmed": True})
    ev.append({"date": (debut + timedelta(days=lockup_days)).isoformat(), "type": "lockup_expiry",
               "label": f"Fim do lock-up ({lockup_days} dias)" + ("" if lockup_confirmed else " — prazo típico, confirmar no prospeto"),
               "confirmed": lockup_confirmed})
    ev.append({"date": (debut + timedelta(days=365)).isoformat(), "type": "ipo_anniversary",
               "label": "1 ano de cotação", "confirmed": True})
    return ev


def overhang(shares_out, float_shares, bars) -> dict:
    vols = [b["v"] for b in bars[-20:] if b.get("v")]
    adv = sum(vols) / len(vols) if vols else None
    locked = shares_out - float_shares if shares_out and float_shares and shares_out > float_shares else None
    return {"shares_outstanding": shares_out, "float_shares": float_shares, "locked_estimate": locked,
            "float_pct": r2(float_shares / shares_out * 100) if shares_out and float_shares else None,
            "adv20": r2(adv, 0), "days_to_trade_locked": r2(locked / adv, 1) if locked and adv else None}


def run(profile, notify=True):
    p = as_dict(profile)
    if not p.get("ipo_recente") or not p.get("first_trade_date"):
        return {"applicable": False, "reason": "não é IPO recente (cotada há mais de 1 ano)", "events": []}
    r = get_router()
    debut = date.fromisoformat(p["first_trade_date"][:10])
    market = p.get("market")
    lock_days, confirmed, source = TYPICAL_LOCKUP.get(market, 180), False, "convenção do mercado"
    if market == "US":
        try:
            lk = r.get("lockup", p["name"]).data
            lock_days, confirmed, source = lk["days"], True, lk["url"]
        except DataUnavailable:
            pass
    try:
        bars = r.get("eod", p["symbol"], days=60).data
    except DataUnavailable:
        bars = []
    evs = events(debut, market, lock_days, confirmed)
    lock_date = debut + timedelta(days=lock_days)
    days_left = (lock_date - date.today()).days
    out = {"applicable": True, "debut": debut.isoformat(), "days_listed": (date.today() - debut).days,
           "lockup": {"date": lock_date.isoformat(), "days": lock_days, "confirmed": confirmed, "source": source,
                      "days_until": days_left},
           "overhang": overhang(p.get("shares_outstanding"), p.get("float_shares"), bars), "events": evs}
    if notify and 0 <= days_left <= 7:
        conn = db.connect()
        key = f"lockup:{p['symbol']}:{lock_date.isoformat()}"
        if not db.was_seen(conn, key):
            oh = out["overhang"]
            msg = (f"{p['symbol']} ({p['name']}): fim do lock-up em {days_left} dia(s), {lock_date.isoformat()}"
                   f"{'' if confirmed else ' (prazo típico, não confirmado)'}.\n"
                   f"Free float {oh['float_pct']}%; dias de negociação para absorver as ações bloqueadas: "
                   f"{oh['days_to_trade_locked']}.\n{DISCLAIMER}")
            out["alert_sent"] = default_notifier().send(msg)
            db.mark_seen(conn, key, "lockup", out["lockup"])
    return out
