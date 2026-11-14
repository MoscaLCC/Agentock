"""Sinal de uma sessão que lidera (Ásia / Europa / EUA) para a abertura da bolsa da ação."""
from core.data import DataUnavailable, get_router
from core.sessions import GROUPS, build_proxies, compute_lead, market_state, now_utc, proxy_move
from core.util import as_dict


def run(profile, group="asia"):
    p = as_dict(profile)
    now = now_utc()
    state = market_state(p.get("calendar"), now)
    proxies = build_proxies(group, p)
    needs_data = state.get("known") and not state.get("open") and p.get("market") not in GROUPS[group]["markets"]
    if needs_data:
        r = get_router()
        for px in proxies:
            try:
                bars = r.get("intraday", px["symbol"], interval="5m", days=5).data
            except DataUnavailable:
                bars = []
            px["move"] = proxy_move(bars, state["last_close"])
    out = compute_lead(group, p.get("market"), state, proxies, now)
    out["symbol"] = p["symbol"]
    return out
