"""Motor de sessões para os sinais entre mercados (2.5a asia_lead, 2.5 europe_lead, 2.6 us_lead).

Ideia: a ação fechou na sua bolsa às T. Que informação nova chegou depois de T, vinda de uma sessão que
negociou entretanto? Proxies por ordem de força: a própria empresa noutra bolsa (1.0), futuros (0.7),
índices (0.5). Peers por região ficam fora por agora (exigiria o 2.12 antes da camada 1).
"""
from datetime import datetime, timezone

import pandas as pd

GROUPS = {
    "asia": {"markets": {"JP", "KR", "HK", "CN"}, "futures": [], "indices": ["^N225", "^KS11", "^HSI", "000001.SS"]},
    "europe": {"markets": {"EU"}, "futures": [], "indices": ["^STOXX50E", "^GDAXI"]},
    "us": {"markets": {"US"}, "futures": ["ES=F", "NQ=F"], "indices": ["^GSPC", "^IXIC"]},
}
WEIGHTS = {"cross_listing": 1.0, "future": 0.7, "index": 0.5}


def market_state(calendar_code: str | None, now: datetime) -> dict:
    """Estado da bolsa da ação: aberta agora? último fecho (UTC)?"""
    if not calendar_code:
        return {"known": False}
    import exchange_calendars as xcals
    cal = xcals.get_calendar(calendar_code)
    ts = pd.Timestamp(now).tz_convert("UTC") if pd.Timestamp(now).tzinfo else pd.Timestamp(now, tz="UTC")
    ts = ts.floor("min")
    try:
        is_open = bool(cal.is_open_on_minute(ts))
    except Exception:
        is_open = False
    last_close = cal.previous_close(ts) if not is_open else cal.previous_close(ts)
    next_open = cal.next_open(ts)
    return {"known": True, "open": is_open, "last_close": last_close.isoformat(), "next_open": next_open.isoformat()}


def _ts(t: str) -> pd.Timestamp:
    x = pd.Timestamp(t)
    return x.tz_localize("UTC") if x.tzinfo is None else x.tz_convert("UTC")


def proxy_move(bars: list[dict], since: str) -> dict | None:
    """Variação de um proxy desde `since` (UTC): último preço antes de `since` → último preço disponível."""
    if not bars:
        return None
    cut = _ts(since)
    before = [b for b in bars if b.get("c") and _ts(b["t"]) < cut]
    after = [b for b in bars if b.get("c") and _ts(b["t"]) >= cut]
    if not before or not after:
        return None
    ref, last = before[-1], after[-1]
    return {"ref_price": ref["c"], "ref_ts": ref["t"], "last_price": last["c"], "last_ts": last["t"],
            "change_pct": round((last["c"] / ref["c"] - 1) * 100, 3), "bars_after": len(after)}


def compute_lead(group: str, target_market: str, state: dict, proxies: list[dict], now: datetime) -> dict:
    """proxies: [{symbol, kind, currency_differs, move (proxy_move ou None)}]"""
    g = GROUPS[group]
    base = {"group": group, "target_market": target_market, "market_state": state}
    if target_market in g["markets"]:
        return {**base, "applicable": False, "reason": "a ação pertence à sessão que lidera"}
    if not state.get("known"):
        return {**base, "applicable": False, "reason": "calendário da bolsa desconhecido"}
    if state.get("open"):
        return {**base, "applicable": False, "reason": "o mercado da ação está aberto: o preço já reflete a informação"}
    used = [p for p in proxies if p.get("move")]
    if not used:
        return {**base, "applicable": False, "reason": "nenhum proxy negociou depois do fecho da ação", "proxies": proxies}
    tot_w, acc = 0.0, 0.0
    for p in used:
        w = WEIGHTS[p["kind"]] * (0.8 if p.get("currency_differs") else 1.0)
        p["weight"] = round(w, 2)
        acc += w * p["move"]["change_pct"]
        tot_w += w
    signal = acc / tot_w
    signs = {1 if p["move"]["change_pct"] > 0 else -1 for p in used if abs(p["move"]["change_pct"]) > 0.05}
    conf = 0.3 + (0.3 if any(p["kind"] == "cross_listing" for p in used) else 0) + min(0.2, 0.05 * len(used))
    if len(signs) > 1:
        conf -= 0.2
    bias = "positivo" if signal > 0.3 else "negativo" if signal < -0.3 else "neutro"
    return {**base, "applicable": True, "signal_pct": round(signal, 3), "bias": bias,
            "confidence": round(max(0.05, min(conf, 0.9)), 2), "proxies": proxies,
            "note": "variações em moeda local; cotações noutra moeda não estão ajustadas ao câmbio (peso reduzido)"}


def build_proxies(group: str, profile: dict) -> list[dict]:
    g = GROUPS[group]
    out = [{"symbol": c["symbol"], "kind": "cross_listing", "currency_differs": True}
           for c in profile.get("cross_listings") or [] if c.get("market") in g["markets"]]
    out += [{"symbol": s, "kind": "future", "currency_differs": False} for s in g["futures"]]
    out += [{"symbol": s, "kind": "index", "currency_differs": False} for s in g["indices"]]
    return out


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
