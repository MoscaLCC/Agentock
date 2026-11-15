"""2.20 — análise de insiders. Sem LLM: regras explícitas sobre as transações (core/data/insiders.py).

Só contam como sinal as compras e vendas em bolsa (código P e S; na Coreia inclui blocos 시간외 em bolsa).
Transferências negociadas fora de bolsa na Coreia (장외, código O — muitas vezes entre familiares) ficam de fora.
Atribuições e bónus em ações (A), exercícios de opções (M), retenções para impostos (F), doações (G) e heranças (W)
ficam de fora — são remuneração ou património, não opinião sobre o preço.
Vendas pré-planeadas pesam pouco: plano 10b5-1 nos EUA, pré-aviso de negociação (거래계획보고) na Coreia.

Regras do sinal (−2 a +2), janela de 90 dias:
  +2  compra em grupo: ≥ 3 insiders diferentes compraram num intervalo de 30 dias
  +1  compra da gestão de topo (CEO, CFO, chairman, presidente) ≥ 100 mil USD,
      ou compras ≥ 0,01% da market cap
  −1  vendas discricionárias (não planeadas) ≥ 0,1% da market cap, ou ≥ 3 vendedores discricionários
  −2  vendas discricionárias ≥ 0,5% da market cap
Compras e vendas somam-se (ex.: CEO compra +1 e três administradores vendem −1 → 0).
"""
from datetime import date, timedelta

from core.data import DataUnavailable, get_router
from core.data.insiders import SENIOR
from core.messages import big_pt, num_pt
from core.util import as_dict, r2

WINDOWS = (30, 90, 180)
LABELS = {2: "muito positivo", 1: "positivo", 0: "neutro", -1: "negativo", -2: "muito negativo"}


def _value(t: dict, price: float | None) -> float | None:
    p = t.get("price") or price
    return t["shares"] * p if p and t.get("shares") else None


def _in_window(txs: list[dict], today: date, days: int) -> list[dict]:
    cut = (today - timedelta(days=days)).isoformat()
    return [t for t in txs if (t.get("date") or "") >= cut]


def money(v: float | None, cur: str = "") -> str:
    """97 482 332 → '97 M USD'; 3.88e12 → '3,88 biliões KRW'."""
    return f"{big_pt(v or 0)} {cur}".strip()


def pct(frac: float) -> str:
    if 0 < frac < 0.00001:
        return "<0,001%"
    return f"{num_pt(frac * 100, 2 if frac >= 0.0001 else 3)}%"


def window_stats(txs: list[dict], today: date, days: int, price: float | None) -> dict:
    w = _in_window(txs, today, days)
    buys = [t for t in w if t["code"] == "P"]
    sells = [t for t in w if t["code"] == "S"]
    bv = sum(_value(t, price) or 0 for t in buys)
    sv = sum(_value(t, price) or 0 for t in sells)
    pv = sum(_value(t, price) or 0 for t in sells if t.get("planned"))
    return {"buys": len(buys), "buyers": len({t["name"] for t in buys}), "buy_value": r2(bv, 0),
            "sells": len(sells), "sellers": len({t["name"] for t in sells}), "sell_value": r2(sv, 0),
            "planned_sell_value": r2(pv, 0),
            "discretionary_sellers": len({t["name"] for t in sells if not t.get("planned")}),
            "net_value": r2(bv - sv, 0)}


def cluster_buy(txs: list[dict], today: date) -> bool:
    """≥ 3 insiders diferentes com compras (P) dentro de um intervalo de 30 dias, nos últimos 90."""
    buys = sorted((t for t in _in_window(txs, today, 90) if t["code"] == "P"), key=lambda t: t["date"])
    for i, t in enumerate(buys):
        end = (date.fromisoformat(t["date"]) + timedelta(days=30)).isoformat()
        if len({b["name"] for b in buys[i:] if b["date"] <= end}) >= 3:
            return True
    return False


def _buy_signal(txs, s90, market_cap, price, today, cur, usd_per_unit) -> tuple[int, str | None]:
    if cluster_buy(txs, today):
        return 2, (f"Compra em grupo: {s90['buyers']} insiders compraram em 90 dias "
                   f"({money(s90['buy_value'], cur)})")
    if not s90["buys"]:
        return 0, None
    min_senior = 100_000 / usd_per_unit if usd_per_unit else 100_000  # 100 mil USD na moeda da ação
    senior = [t for t in _in_window(txs, today, 90)
              if t["code"] == "P" and t.get("role_class") in SENIOR and (_value(t, price) or 0) >= min_senior]
    if senior:
        v = sum(_value(t, price) or 0 for t in senior)
        who = senior[0].get("role") or "Gestão de topo"
        return 1, f"Gestão de topo comprou: {who} ({senior[0]['name']}), {money(v, cur)} em 90 dias"
    frac = s90["buy_value"] / market_cap if market_cap else 0
    if frac >= 0.0001:
        return 1, (f"Compras de {s90['buyers']} insiders: {money(s90['buy_value'], cur)} em 90 dias "
                   f"({pct(frac)} da market cap)")
    return 0, f"Compras pequenas de insiders: {money(s90['buy_value'], cur)} em 90 dias (peso baixo)"


def _sell_signal(s90, market_cap, cur, plan_word) -> tuple[int, str | None]:
    if not s90["sells"]:
        return 0, None
    disc = (s90["sell_value"] or 0) - (s90["planned_sell_value"] or 0)
    if disc <= 0:
        return 0, f"Vendas de {money(s90['sell_value'], cur)} em 90 dias, todas {plan_word}: sinal fraco"
    frac = disc / market_cap if market_cap else 0
    planned = (s90["planned_sell_value"] or 0) / s90["sell_value"] if s90["sell_value"] else 0
    tail = f" ({pct(frac)} da market cap" + (f"; {num_pt(planned * 100, 0)}% das vendas {plan_word})"
                                             if planned else ")")
    if frac >= 0.005:
        return -2, f"Vendas discricionárias fortes: {money(disc, cur)} em 90 dias{tail}"
    if frac >= 0.001 or s90["discretionary_sellers"] >= 3:
        return -1, (f"Vendas discricionárias de {s90['discretionary_sellers']} insiders: "
                    f"{money(disc, cur)} em 90 dias{tail}")
    return 0, f"Vendas discricionárias de {money(disc, cur)} em 90 dias{tail}: peso baixo"


def score(txs: list[dict], stats: dict, market_cap: float | None, price: float | None, today: date,
          cur: str = "", usd_per_unit: float | None = None, korea: bool = False) -> tuple[int, list[str]]:
    """Devolve (score −2..+2, sinais em português com os números que os justificam)."""
    s90 = stats[90]
    plan_word = "com pré-aviso (거래계획보고)" if korea else "em plano 10b5-1"
    b, bt = _buy_signal(txs, s90, market_cap, price, today, cur, usd_per_unit)
    s, st = _sell_signal(s90, market_cap, cur, plan_word)
    signals = [x for x in (bt, st) if x] or ["Sem compras nem vendas de insiders nos últimos 90 dias"]
    return max(-2, min(2, b + s)), signals


def notable(txs: list[dict], price: float | None, n: int = 6) -> list[dict]:
    """Maiores transações em 180 dias: compras e vendas, mais doações, heranças e transferências fora de bolsa
    (contexto, sem peso no sinal)."""
    rows = [t for t in txs if t["code"] in ("P", "S", "G", "W", "O")]
    rows.sort(key=lambda t: _value(t, price) or 0, reverse=True)
    return [{"date": t["date"], "name": t["name"], "role": t.get("role"), "code": t["code"], "kind": t["kind"],
             "shares": t["shares"], "price": t.get("price"), "value": r2(_value(t, price), 0),
             "planned": t.get("planned", False), "note": t.get("note"),
             "controlling": t.get("controlling", False)} for t in rows[:n]]


def analyse(txs: list[dict], price: float | None, market_cap: float | None, source: str, today: date,
            cur: str = "", usd_per_unit: float | None = None, korea: bool = False) -> dict:
    stats = {d: window_stats(txs, today, d, price) for d in WINDOWS}
    sc, signals = score(txs, stats, market_cap, price, today, cur, usd_per_unit, korea)
    w180 = _in_window(txs, today, 180)
    unread = sum(1 for t in w180 if t["code"] in ("INC", "DEC"))
    if unread:
        signals.append(f"{unread} relatórios pequenos sem motivo lido (aumentos/reduções), fora do sinal")
    if source == "finnhub":  # alternativa sem cargo nem plano 10b5-1: as vendas parecem todas discricionárias
        sc = max(-1, min(1, sc))
        signals.append("Fonte alternativa (Finnhub): sem cargo nem indicação de plano 10b5-1; sinal limitado a ±1")
    head = signals[0]
    return {"available": True, "source": source, "score": sc, "label": LABELS[sc], "signals": signals,
            "headline": f"Insiders {LABELS[sc]}: {head[0].lower()}{head[1:]}",
            "windows": {str(k): v for k, v in stats.items()}, "notable": notable(txs, price),
            "routine_180d": {k: sum(1 for t in w180 if t["code"] in c) for k, c in
                             (("atribuições", "A"), ("exercícios", "MX"), ("impostos", "F"),
                              ("doações", "G"), ("heranças", "W"))},
            "currency": cur}


def run(profile):
    p = as_dict(profile)
    market, sym = p.get("market"), p["symbol"]
    if market not in ("US", "KR"):
        return {"available": False, "score": None, "symbol": sym,
                "reason": "sem fonte estruturada de insiders para este mercado (só EUA via SEC e Coreia via DART)"}
    r = get_router()
    try:
        res = r.get("insider_transactions", sym, days=180)
    except DataUnavailable:
        return {"available": False, "score": None, "symbol": sym,
                "reason": "sem transações de insiders reportadas em 180 dias (emitentes estrangeiros/ADRs não "
                          "entregam Form 4)" if market == "US" else "sem relatórios na DART em 180 dias"}
    mc, mc_usd = p.get("market_cap"), p.get("market_cap_usd")
    out = analyse(res.data, p.get("price"), mc, res.provider, date.today(), p.get("currency") or "",
                  mc_usd / mc if mc and mc_usd else None, korea=market == "KR")
    out["symbol"] = sym
    if market == "US":
        try:
            out["mspr_avg_3m"] = r.get("insider", sym).data.get("mspr_avg_3m")  # Finnhub: sentimento agregado
        except DataUnavailable:
            out["mspr_avg_3m"] = None
    return out
