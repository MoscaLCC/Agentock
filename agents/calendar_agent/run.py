"""2.14 — eventos datados que mexem com o preço, por ordem cronológica."""
from datetime import date

from core.data import DataUnavailable, get_router
from core.util import as_dict


def build(cal: dict | None, lifecycle: dict | None, today: date | None = None) -> dict:
    today = today or date.today()
    events = []

    def add(d, typ, label, confirmed=True, extra=None):
        if not d:
            return
        try:
            dd = date.fromisoformat(str(d)[:10])
        except ValueError:
            return
        events.append({"date": dd.isoformat(), "type": typ, "label": label, "days_until": (dd - today).days,
                       "confirmed": confirmed, **(extra or {})})

    cal = cal or {}
    for d in cal.get("earnings_dates") or []:
        add(d, "earnings", "Apresentação de resultados")
    add(cal.get("ex_dividend"), "ex_dividend", "Data ex-dividendo")
    add(cal.get("dividend_date"), "dividend", "Pagamento de dividendo")
    for ev in (lifecycle or {}).get("events") or []:
        add(ev.get("date"), ev.get("type"), ev.get("label"), ev.get("confirmed", True))

    events.sort(key=lambda e: e["date"])
    upcoming = [e for e in events if e["days_until"] >= 0]
    nxt = next((e for e in upcoming if e["type"] == "earnings"), None)
    return {
        "events": events, "upcoming": upcoming,
        "next_earnings": nxt["date"] if nxt else None, "days_to_earnings": nxt["days_until"] if nxt else None,
        "earnings_within_14d": bool(nxt and nxt["days_until"] <= 14),
        "estimates": {"eps_avg": cal.get("eps_estimate_avg"), "revenue_avg": cal.get("revenue_estimate_avg")},
    }


def run(profile, lifecycle=None):
    p = as_dict(profile)
    try:
        cal = get_router().get("calendar", p["symbol"]).data
    except DataUnavailable:
        cal = None
    out = build(cal, as_dict(lifecycle))
    out["symbol"] = p["symbol"]
    out["source_available"] = cal is not None
    return out
