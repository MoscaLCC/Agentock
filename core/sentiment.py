"""Sentimento por código (D28). A rubrica é aritmética: recalculada em Python dava o mesmo que o LLM nos dossiers
gravados (diferença ≤ 0,04; rótulo e tendência iguais em 4 de 4), e o LLM gastava 13–23 s do caminho crítico.

Notícias   tom (+1 / 0 / −1) × peso da relevância (5→3, 4→2, 3→1, 2→0,5, 1→0,25); score = soma ÷ soma dos pesos.
           Nenhum item pesa mais de 35% do total (uma notícia de fonte única não decide o sentimento sozinha).
Analistas  consensus_score (−2…+2) ÷ 2, ±0,1 pela tendência do consenso e ±0,1 pelo saldo de revisões em 90 dias.
Insiders   score do insiders_agent (−2…+2) ÷ 2 (as regras já foram aplicadas lá).
Agregado   50% notícias, 35% analistas, 15% insiders (redistribui se faltar uma fonte).
Tendência  score das janelas 4h+24h menos o das 7d+30d: > +0,2 a melhorar; < −0,2 a piorar; senão estável.
"""
REL_WEIGHT = {5: 3.0, 4: 2.0, 3: 1.0, 2: 0.5, 1: 0.25}
TONE = {"positivo": 1, "negativo": -1, "neutro": 0}
SOURCE_WEIGHT = {"news": 0.50, "analysts": 0.35, "insiders": 0.15}
MAX_ITEM_SHARE = 0.35


def _num(x: float) -> str:
    return f"{x:.2f}".replace(".", ",").replace("-", "−")


def news_score(items: list[dict]) -> tuple[float | None, dict]:
    """(score −1…+1 ou None, contagens). Só itens triados (com relevância) contam."""
    rated = [i for i in items or [] if i.get("relevance") in REL_WEIGHT]
    counts = {"total": len(rated), "positivo": 0, "negativo": 0, "neutro": 0,
              "untriaged": len(items or []) - len(rated)}
    if not rated:
        return None, counts
    weights = [REL_WEIGHT[i["relevance"]] for i in rated]
    total = sum(weights)
    if len(rated) >= 3:  # teto por item: redistribui o excesso pelos outros de forma implícita
        cap = MAX_ITEM_SHARE * total
        weights = [min(w, cap) for w in weights]
        total = sum(weights)
    acc = 0.0
    for i, w in zip(rated, weights):
        tone = i.get("tone") if i.get("tone") in TONE else "neutro"
        counts[tone] += 1
        acc += TONE[tone] * w
    return max(-1.0, min(1.0, acc / total)), counts


def analysts_score(a: dict | None) -> tuple[float | None, str]:
    if not a or a.get("consensus_score") is None:
        return None, "sem consenso de analistas disponível"
    base = a["consensus_score"] / 2
    adj, notes = 0.0, []
    trend = a.get("trend")
    if trend is not None and abs(trend) >= 0.1:
        adj += 0.1 if trend > 0 else -0.1
        notes.append(f"consenso a {'subir' if trend > 0 else 'descer'} ({_num(trend)} em 3 meses)")
    ch = a.get("changes_90d") or {}
    net = ch.get("net")
    if net:
        adj += 0.1 if net > 0 else -0.1
        notes.append(f"{ch.get('up', 0)} subidas e {ch.get('down', 0)} descidas de recomendação em 90 dias")
    c = a.get("counts") or {}
    buy, sell = (c.get("strong_buy") or 0) + (c.get("buy") or 0), (c.get("sell") or 0) + (c.get("strong_sell") or 0)
    basis = (f"{a.get('n_analysts') or buy + sell + (c.get('hold') or 0)} analistas: {buy} compra, "
             f"{c.get('hold') or 0} manter, {sell} venda; consenso {_num(a['consensus_score'])} em ±2")
    return max(-1.0, min(1.0, base + adj)), basis + ("; " + "; ".join(notes) if notes else "")


def insiders_score(ins: dict | None) -> tuple[float | None, str]:
    if not ins:
        return None, "insiders não analisados nesta execução"
    if ins.get("available") is False:
        return None, ins.get("reason") or "sem fonte de insiders para este mercado"
    if ins.get("score") is None:
        return None, "sem sinal de insiders"
    signals = ins.get("signals") or []
    return max(-1.0, min(1.0, ins["score"] / 2)), (signals[0] if signals else f"sinal de insiders {ins['score']} em ±2")


def label_of(x: float) -> str:
    return "muito negativo" if x <= -0.6 else "negativo" if x <= -0.2 else "neutro" if x < 0.2 else \
        "positivo" if x < 0.6 else "muito positivo"


def compute(news: dict | None, analysts: dict | None, insiders: dict | None) -> dict:
    items = (news or {}).get("items") or []
    n_score, counts = news_score(items)
    a_score, a_basis = analysts_score(analysts)
    i_score, i_basis = insiders_score(insiders)
    if news is None:
        n_basis = "notícias indisponíveis nesta execução"
    elif not counts["total"]:
        n_basis = "sem notícias triadas nos últimos 30 dias" + (f" ({counts['untriaged']} por triar)" if counts["untriaged"] else "")
    else:
        n_basis = (f"{counts['total']} notícias únicas em 30 dias, ponderadas pela relevância: {counts['positivo']} positivas, "
                   f"{counts['negativo']} negativas, {counts['neutro']} neutras"
                   + (f"; {counts['untriaged']} recentes por triar" if counts["untriaged"] else ""))
    parts = {"news": n_score, "analysts": a_score, "insiders": i_score}
    avail = {k: v for k, v in parts.items() if v is not None}
    overall = sum(v * SOURCE_WEIGHT[k] for k, v in avail.items()) / sum(SOURCE_WEIGHT[k] for k in avail) if avail else 0.0

    short, _ = news_score([i for i in items if i.get("w") in ("4h", "24h")])
    long_, _ = news_score([i for i in items if i.get("w") in ("7d", "30d")])
    if short is None or long_ is None:
        trend, trend_note = "estável", "sem notícias suficientes nas duas metades para medir a tendência"
    else:
        diff = short - long_
        trend = "a melhorar" if diff > 0.2 else "a piorar" if diff < -0.2 else "estável"
        trend_note = f"últimas 24 h {_num(short)} vs. 1–30 dias {_num(long_)}"

    top = sorted([i for i in items if i.get("relevance")], key=lambda i: (-i["relevance"], i.get("w") != "4h"))
    drivers = [f"Notícia {i['tone']} (relevância {i['relevance']}, {i['w']}): {i.get('summary') or i.get('title')}"
               for i in top[:3] if i["tone"] != "neutro" or i["relevance"] >= 4]
    if a_score is not None:
        drivers.append("Analistas: " + a_basis)
    if i_score is not None and abs(i_score) >= 0.5:
        drivers.append("Insiders: " + i_basis)
    label = label_of(overall)
    named = (("notícias", n_score), ("analistas", a_score), ("insiders", i_score))
    have = " · ".join(f"{name} {_num(v)}" for name, v in named if v is not None)
    missing = ", ".join(name for name, v in named if v is None)
    summary = f"Sentimento {label} ({_num(overall)} em ±1), {trend}." + (f" {have}." if have else "") + \
        (f" Sem dados de: {missing}." if missing else "")
    return {
        "overall_score": round(overall, 2), "label": label, "trend": trend, "trend_note": trend_note,
        "news": {"score": None if n_score is None else round(n_score, 2), "basis": n_basis},
        "analysts": {"score": None if a_score is None else round(a_score, 2), "basis": a_basis},
        "insiders": {"score": None if i_score is None else round(i_score, 2), "basis": i_basis},
        "drivers": drivers[:4], "score": max(-2, min(2, round(overall * 2.5))), "summary": summary,
        "method": "calculado por código: 50% notícias (tom × relevância), 35% analistas, 15% insiders",
    }
