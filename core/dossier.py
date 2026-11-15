"""Dossier compacto para a classificação (D26). Feito por código, a partir dos outputs dos nós.

O dossier antigo levava os 23 outputs inteiros: 45 mil caracteres, lidos 3 vezes (juiz, bull, bear). Medido nos
dossiers gravados: 25 mil caracteres chegam (−45%) sem perder nenhum dos 150 números que o juiz citou.

Regras:
- fica o que sustenta uma razão ou um risco; saem metadados (fontes, fornecedores, horas de recolha), campos
  repetidos entre nós e resumos em prosa de números que já lá estão;
- uma dimensão em falta fica `null` (lacuna declarada: a rubrica desconta confiança) — nunca é omitida;
- as notícias vão numa lista única, sem repetidos, com a janela em `w`;
- os caminhos são estáveis: o juiz cita `fundamental_data.valuation.forward_pe` e o guard confere esse campo.
"""
from .util import as_dict

# ordem = ordem das dimensões na rubrica de classificação
SECTIONS = ("profile", "indicators", "technical", "calendar", "analysts", "price_targets", "health", "fundamental",
            "fundamental_data", "comps", "market_share", "relations", "ipo_lifecycle", "asia_lead", "europe_lead",
            "us_lead", "news", "insiders", "sentiment", "timing", "forecast")


def keep(d, keys) -> dict:
    return {k: d[k] for k in keys if isinstance(d, dict) and k in d}


def drop(d, keys) -> dict:
    return {k: v for k, v in d.items() if k not in keys} if isinstance(d, dict) else d


def _profile(p: dict) -> dict:
    return keep(p, ("symbol", "name", "market", "exchange", "currency", "sector", "industry", "country", "price",
                    "change_pct", "market_cap_usd", "ipo_recente", "days_listed"))


def _analysts(a: dict) -> dict:
    a = drop(a, ("sources", "symbol"))
    a["recent_changes"] = [keep(x, ("date", "firm", "action", "to_grade", "price_target", "prior_price_target"))
                           for x in (a.get("recent_changes") or [])[:3]]
    return a


def _price_targets(p: dict) -> dict:
    p = drop(p, ("sources", "symbol"))
    p["recent_firm_targets"] = (p.get("recent_firm_targets") or [])[:3]
    return p


def _health(h: dict) -> dict:
    h = drop(h, ("formulas", "fiscal_years", "benchmark", "symbol"))
    pio = h.get("piotroski")
    if isinstance(pio, dict) and isinstance(pio.get("tests"), dict):
        h["piotroski"] = {"points": pio.get("points"), "available": pio.get("available"),
                          "failed": [k for k, v in pio["tests"].items() if v is False]}
    if isinstance(h.get("momentum"), dict):
        h["momentum"] = drop(h["momentum"], ("benchmark_pct",))
    return h


def _comps(c: dict) -> dict:
    cols = ("symbol", "overlap", "size_ratio", "trailing_pe", "forward_pe", "ev_to_ebitda", "operating_margin",
            "revenue_growth", "ret_12m_pct")
    return {"target": drop(c.get("target") or {}, ("name", "currency", "market_cap")), "medians": c.get("medians"),
            "peers": [keep(x, cols) for x in c.get("peers") or []]}


def _market_share(m: dict) -> dict:
    m = drop(m, ("sources", "industry"))
    m["players"] = [keep(x, ("name", "share_pct", "year")) for x in m.get("players") or [] if x.get("share_pct") is not None]
    m["moat_notes"] = (m.get("moat_notes") or [])[:2]
    return m


def _relations(r: dict) -> dict:
    r = drop(r, ("sources",))
    r["related"] = [{**keep(x, ("name", "relation", "symbol", "stake_pct", "recent_change_pct")),
                     "note": (x.get("note") or "")[:120]}
                    for x in r.get("related") or [] if x.get("importance") == "alta"]
    return r


def _lead(v: dict) -> dict:
    return keep(v, ("applicable", "reason", "bias", "signal_pct", "confidence"))


def _news(n: dict) -> dict:
    items = []
    for it in n.get("items") or []:
        e = {"w": it.get("w"), **keep(it, ("title", "source", "category", "relevance", "tone")),
             "at": (it.get("published_at") or "")[:16]}
        if (it.get("relevance") or 0) >= 3 and it.get("summary"):
            e["summary"] = it["summary"]
        if it.get("triaged") is False:
            e["por_triar"] = True
        items.append(e)
    return {"per_window": n.get("per_window"), "items": items, **({"note": n["note"]} if n.get("note") else {})}


def _insiders(i: dict) -> dict:
    i = drop(i, ("symbol", "source", "currency"))
    if isinstance(i.get("notable"), list):
        i["notable"] = [drop(t, ("code", "controlling")) for t in i["notable"][:4]]
    return i


RULES = {
    "profile": _profile,
    "indicators": lambda d: drop(d, ("symbol", "provider", "currency", "bars", "window_days", "available")),
    "technical": lambda d: drop(d, ("summary",)),
    "calendar": lambda d: drop(d, ("events", "symbol", "source_available")),
    "analysts": _analysts, "price_targets": _price_targets, "health": _health,
    "fundamental": lambda d: drop(d, ("summary",)),
    "fundamental_data": lambda d: drop(d, ("symbol", "currency", "fiscal_years")),
    "comps": _comps, "market_share": _market_share, "relations": _relations,
    "ipo_lifecycle": lambda d: d,
    "asia_lead": _lead, "europe_lead": _lead, "us_lead": _lead,
    "news": _news, "insiders": _insiders,
    "sentiment": lambda d: drop(d, ("summary", "method")),
    "timing": lambda d: drop(d, ("summary",)),
    "forecast": lambda d: d,   # o resumo dos cenários tem números que só existem lá
}


def build(inputs: dict) -> dict:
    """{secção: output do nó ou None} → dossier compacto, com as lacunas a `null` e listadas em `gaps`."""
    out = {}
    for name in SECTIONS:
        v = as_dict(inputs.get(name))
        out[name] = RULES[name](dict(v)) if isinstance(v, dict) else None
    out["gaps"] = [k for k in SECTIONS if out[k] is None]
    return out
