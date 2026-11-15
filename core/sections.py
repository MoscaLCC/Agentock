"""Cartão (imagem + legenda + botões) e secções a pedido para o Telegram.

Princípio: pouco texto à primeira vista (o cartão), detalhe só quando se toca num botão; tabelas em <pre>
(monoespaçado, ≤ 36 colunas para caber no telemóvel).
"""
import html
import re

from . import charts, messages as M, news as news_mod, report_data
from .data import DataUnavailable, get_router
from .ratings import Rating
from .telegram import keyboard

SECTIONS = [("rz", "🧾 Porquê"), ("rk", "⚠️ Riscos"), ("sc", "🎯 Cenários"),
            ("db", "🥊 Debate"), ("pr", "🏢 Comparáveis"), ("nw", "📰 Notícias"), ("in", "👔 Insiders")]


def news_of(outputs: dict) -> dict | None:
    """Notícias de uma análise: o nó `news` (Fase 10) ou, em análises antigas, as 4 janelas fundidas."""
    if outputs.get("news"):
        return outputs["news"]
    return news_mod.legacy_digest({w: outputs.get(f"news_{w}") for w, _ in news_mod.WINDOWS})


def available(data: dict) -> list[str]:
    """Secções com conteúdo nesta análise (um botão que responde "sem dados" só faz perder um toque)."""
    o, p = data.get("outputs") or {}, data.get("payload") or {}
    has = {"rz": bool(data.get("reasons")), "rk": bool(p.get("risks")),
           "sc": bool((o.get("forecast") or {}).get("scenarios")),
           "db": bool((p.get("debate") or {}).get("bull") or (p.get("debate") or {}).get("bear")),
           "pr": bool((o.get("comps") or {}).get("peers")),
           "nw": bool((news_of(o) or {}).get("items")),
           "in": bool((o.get("insiders") or {}).get("available"))}
    return [k for k, _ in SECTIONS if has[k]]


def buttons(row_id: int, data: dict | None = None, actions: bool = False) -> dict:
    """Botões das secções (só as que têm dados, se `data` vier) e, com `actions`, a linha de ações da ação."""
    keys = available(data) if data else [k for k, _ in SECTIONS]
    cb = [(label, f"s|{row_id}|{key}") for key, label in SECTIONS if key in keys]
    rows = [cb[i:i + 3] for i in range(0, len(cb), 3)]  # 3 por linha: os rótulos cabem sem cortes no telemóvel
    if actions and data:
        t = data["run"]["ticker"]
        rows.append([("⭐ Seguir", f"w|add|{t}"), ("🔁 Reanalisar", f"r|{t}"), ("📈 Histórico", f"h|{t}")])
    return keyboard(rows)


def card_png(data: dict) -> bytes:
    try:
        bars = get_router().get("eod", data["run"]["ticker"], days=400).data
    except DataUnavailable:
        bars = []
    return charts.stock_card(data, bars)


def caption(data: dict, note: str | None = None) -> str:
    """Legenda do cartão: o que a imagem não diz (frase-resumo e pontos-chave)."""
    p, run = data["payload"], data["run"]
    rating = Rating(run["rating"])
    name = M.shorten(M.short_name((data["outputs"].get("profile") or {}).get("name")) or run["ticker"], 30)
    price = f" · {M.price_pt(run['price'])} {run['currency'] or ''}".rstrip() if run["price"] is not None else ""
    lines = [f"{M.EMOJI_RATING[int(rating)]} <b>{M.esc(name)} — {M.esc(rating.label.upper())}</b> · "
             f"{(run['confidence'] or 0):.0%}{M.esc(price)}"]
    if note:
        lines.append(f"<i>Pedido: {M.esc(M.shorten(note.split(';')[0], 90))}</i>")
    if p.get("headline"):
        lines += ["", f"<i>{M.esc(M.shorten(p['headline'], 130))}</i>"]
    points = p.get("key_points") or [M.point_of(r) for r in data["reasons"][:3]]
    lines += [""] + [f"• {M.esc(M.shorten(x, 80))}" for x in points[:3]]
    lines += ["", f"<i>{M.esc(M.when_pt(run['ts']) or '')} (Lisboa) · {M.DISCLAIMER_SHORT}</i>"]
    return "\n".join(lines)


def short_caption(data: dict) -> str:
    """Legenda mínima do cartão quando o veredicto já foi enviado em texto (o bot)."""
    run = data["run"]
    name = M.shorten(M.short_name((data["outputs"].get("profile") or {}).get("name")) or run["ticker"], 30)
    return (f"<b>{M.esc(name)}</b> · {M.esc(run['ticker'])} · {M.esc(M.when_pt(run['ts']) or '')} (Lisboa)\n"
            f"<i>Toca na imagem para ampliar. {M.DISCLAIMER_SHORT}</i>")


# ------------------------------------------------------------------ secções
def _bold_prefix(text: str) -> str:
    m = re.match(r"^([^:]{2,40}):\s*(.+)$", text, re.S)
    return f"<b>{M.esc(m.group(1))}</b>: {M.esc(m.group(2))}" if m else M.esc(text)


def _title(data: dict, name: str) -> str:
    run = data["run"]
    when = M.when_pt(run.get("ts"), False)
    return f"<b>{name}</b> · {M.esc(run['ticker'])}" + (f" · <i>{M.esc(when)}</i>" if when else "")


def sec_reasons(data: dict) -> str:
    return "\n".join([_title(data, "Razões"), ""] +
                     [f"{i}. {_bold_prefix(r)}" for i, r in enumerate(data["reasons"], 1)])


def sec_risks(data: dict) -> str:
    risks = data["payload"].get("risks") or []
    body = [f"• {_bold_prefix(r)}" for r in risks] or ["Sem riscos registados."]
    gaps = data["payload"].get("data_gaps") or []
    if gaps:
        from .errors import NODE_LABEL
        body += ["", M.esc("Sem dados nesta análise: " + ", ".join(NODE_LABEL.get(g, g) for g in gaps))]
    g = data["payload"].get("guard") or {}
    if g.get("checked"):
        bad = len(g.get("unverified") or []) + len(g.get("dates_unverified") or [])
        strong = f", {g['by_path']} no campo de origem" if g.get("by_path") else ""
        body += ["", "<i>" + M.esc(f"Números conferidos contra os dados: {g['checked'] - bad} de {g['checked']}{strong}.") + "</i>"]
    for w in (data["payload"].get("warnings") or [])[:2]:
        body.append("⚠️ " + M.esc(M.shorten(w, 160)))
    return "\n".join([_title(data, "Riscos"), ""] + body)


def sec_debate(data: dict) -> str:
    d = data["payload"].get("debate") or {}
    if not (d.get("bull") or d.get("bear")):
        return _title(data, "Debate") + "\n\nEsta análise não teve debate (classificação v1)."
    out = [_title(data, "Debate"), "", f"👍 <b>A favor</b>\n{M.esc(d.get('bull') or '—')}", "",
           f"👎 <b>Contra</b>\n{M.esc(d.get('bear') or '—')}"]
    for label, key in (("Argumentos a favor", "bull_full"), ("Argumentos contra", "bear_full")):
        args = [ln for ln in (d.get(key) or "").split("\n") if ln[:1].isdigit()][:3]
        if args:  # os 3 argumentos mais fortes de cada analista, sem os nomes dos campos entre parênteses
            out += ["", f"<b>{label}</b>"] + [M.esc(M.shorten(re.sub(r"\s*\([a-z_.\[\]0-9, ]+\)", "", a), 230)) for a in args]
    return "\n".join(out)


def _cell(v, nd: int = 1, suffix: str = "", sign: bool = False, width: int = 6) -> str:
    if v is None:
        return "—".rjust(width)
    s = M.num_pt(v, nd) + suffix
    if sign and v > 0:
        s = "+" + s
    return s.rjust(width)


def sec_peers(data: dict) -> str:
    comps = data["outputs"].get("comps") or {}
    rows = ([comps["target"]] if comps.get("target") else []) + (comps.get("peers") or [])
    if not rows:
        return _title(data, "Comparáveis") + "\n\nSem tabela de comparáveis nesta análise."
    head = f"{'':10}{'P/E':>6}{'EV/EB':>6}{'Marg.':>6}{'12 m':>7}"
    lines = [head]
    for i, r in enumerate(rows[:8]):
        name = (r["symbol"] + ("*" if i == 0 and comps.get("target") else ""))[:10]
        lines.append(f"{name:10}{_cell(r.get('forward_pe') or r.get('trailing_pe'))}{_cell(r.get('ev_to_ebitda'))}"
                     f"{_cell(r.get('operating_margin'), 0, '%')}{_cell(r.get('ret_12m_pct'), 0, '%', True, 7)}")
    med = comps.get("medians") or {}
    lines.append(f"{'mediana':10}{_cell(med.get('forward_pe') or med.get('trailing_pe'))}{_cell(med.get('ev_to_ebitda'))}"
                 f"{_cell(med.get('operating_margin'), 0, '%')}{_cell(med.get('ret_12m_pct'), 0, '%', True, 7)}")
    legend = ("P/E: preço ÷ lucro esperado nos próximos 12 meses · EV/EB: valor da empresa ÷ EBITDA · "
              "Marg.: margem operacional · 12 m: retorno da ação em 12 meses. * = esta empresa")
    return "\n".join([_title(data, "Comparáveis"), f"<pre>{M.esc(chr(10).join(lines))}</pre>", f"<i>{legend}</i>"])


def sec_scenarios(data: dict) -> str:
    fc, price = data["outputs"].get("forecast") or {}, data["run"]["price"]
    sc = fc.get("scenarios") or []
    if not sc or not price:
        return _title(data, "Cenários") + "\n\nSem cenários nesta análise."
    names = {"bear": "pessimista", "base": "base", "bull": "otimista"}
    lines = [f"{'':10}{'prob':>5}{'1 mês':>7}{'3 meses':>8}{'12 m':>7}"]  # 37 colunas
    for s in sc:
        ch = [(s[k] / price - 1) * 100 for k in ("price_1m", "price_3m", "price_12m")]
        lines.append(f"{names.get(s['name'], s['name']):10}{s['probability'] * 100:>4.0f}%"
                     f"{_cell(ch[0], 0, '%', True, 7)}{_cell(ch[1], 0, '%', True, 8)}{_cell(ch[2], 0, '%', True, 7)}")
    cur = data["run"]["currency"] or ""
    out = [_title(data, "Cenários"), f"<pre>{M.esc(chr(10).join(lines))}</pre>",
           M.esc(f"Variação face ao preço atual ({M.price_pt(price)} {cur}).")]
    if fc.get("expected_12m"):
        exp = fc["expected_12m"]
        out.append(M.esc(f"Esperado a 12 meses: {M.price_pt(exp)} {cur} ({'+' if exp >= price else ''}"
                         f"{M.num_pt((exp / price - 1) * 100, 1)}%)."))
    if fc.get("summary"):  # o LLM escreve por vezes markdown (**…**): no Telegram sairia em bruto
        out += ["", f"<i>{M.esc(M.shorten(re.sub(r'[*_`#]+', '', fc['summary']), 300))}</i>"]
    return "\n".join(out)


def sec_news(data: dict) -> str:
    digest = news_of(data["outputs"]) or {}
    items = [i for i in digest.get("items") or [] if i.get("title")]
    if not items:
        return _title(data, "Notícias") + "\n\nSem notícias nesta análise."
    items.sort(key=lambda i: i.get("published_at") or "", reverse=True)   # mais recentes primeiro…
    items.sort(key=lambda i: -(i.get("relevance") or 0))                  # …dentro da mesma relevância (estável)
    tone = {"positivo": "🟢", "negativo": "🔴"}
    lines = [_title(data, "Notícias"), ""]
    for it in items[:6]:
        when = M.when_pt(it.get("published_at"), it.get("w") in ("4h", "24h")) or ""
        title = M.esc(M.shorten(it["title"], 90))
        url = str(it.get("url") or "")
        link = f'<a href="{html.escape(url, quote=True)}">{title}</a>' if url.startswith("http") else title
        mark = "🆕" if it.get("triaged") is False else tone.get(it.get("tone"), "⚪")
        lines.append(f"{mark} {link} — {M.esc(it.get('source') or '')} · {M.esc(when)}")
    pw = digest.get("per_window") or {}
    if pw:
        lines += ["", "<i>" + M.esc(f"Nesta análise: {pw.get('4h', 0)} nas últimas 4 h · {pw.get('24h', 0)} em 24 h · "
                                    f"{pw.get('7d', 0)} na semana · {pw.get('30d', 0)} no mês. 🟢 positiva 🔴 negativa") + "</i>"]
    return "\n".join(lines)


def short_money(v: float | None) -> str:
    """Valor compacto para tabelas: 350 k · 97 M · 1,9 mM (mil milhões) · 3,9 B (biliões)."""
    a = abs(v or 0)
    for div, unit in ((1e12, "B"), (1e9, "mM"), (1e6, "M"), (1e3, "k")):
        if a >= div:
            return f"{M.num_pt(v / div, 1 if a < 10 * div else 0)} {unit}"
    return M.num_pt(v or 0, 0)


SOURCES = {"sec": "SEC Form 4", "dart": "DART (Coreia)", "finnhub": "Finnhub"}


def _person(name: str | None) -> str:
    n = name or "—"
    return n.title() if n.isupper() else n  # 'COOK TIMOTHY D' → 'Cook Timothy D'


def sec_insiders(data: dict) -> str:
    ins = data["outputs"].get("insiders") or {}
    if not ins.get("available"):
        return _title(data, "Insiders") + "\n\n" + M.esc(f"Sem dados de insiders: {ins.get('reason') or 'não analisado'}.")
    cur = ins.get("currency") or ""
    sc = ins.get("score") or 0
    head = (f"<b>{M.esc(ins['label'].capitalize())}</b> ({'+' if sc > 0 else ''}{sc}) · "
            f"fonte: {M.esc(SOURCES.get(ins.get('source'), ins.get('source') or ''))}")
    def cell(value, n):
        return f"{short_money(value)} ({n})" if n else "—"

    lines = [f"{'':5}{'compras':>12}{'vendas':>12}{'saldo':>8}"]  # 37 colunas
    for d in ("30", "90", "180"):
        w = (ins.get("windows") or {}).get(d) or {}
        net = w.get("net_value") or 0
        lines.append(f"{d + ' d':5}{cell(w.get('buy_value'), w.get('buys')):>12}"
                     f"{cell(w.get('sell_value'), w.get('sells')):>12}"
                     f"{(('+' if net > 0 else '') + short_money(net)) if net else '—':>8}")
    out = [_title(data, "Insiders"), head, ""] + [f"• {M.esc(x)}" for x in ins.get("signals") or []]
    out += [f"<pre>{M.esc(chr(10).join(lines))}</pre>",
            f"<i>Compras e vendas em bolsa, em {M.esc(cur)} (n.º de transações). "
            "k mil · M milhões · mM mil milhões · B biliões</i>"]
    notable = ins.get("notable") or []
    if notable:
        out += ["", "<b>Maiores transações</b> (180 dias)"]
        for t in notable[:5]:
            extra = [x for x in ("plano 10b5-1" if t.get("planned") and ins.get("source") == "sec" else
                                 "com pré-aviso" if t.get("planned") else None, t.get("note")) if x]
            out.append(f"{M.esc(M.date_pt(t['date']) or '')} · {M.esc(_person(t['name']))}"
                       f" ({M.esc(t.get('role') or '—')}) · {M.esc(t['kind'])} "
                       f"{M.esc(short_money(t.get('value')))} {M.esc(cur)}"
                       + (f" · <i>{M.esc('; '.join(extra))}</i>" if extra else ""))
    routine = {k: v for k, v in (ins.get("routine_180d") or {}).items() if v}
    if routine:
        one = {"atribuições": "atribuição", "exercícios": "exercício", "impostos": "imposto", "doações": "doação",
               "heranças": "herança"}
        items = ", ".join(f"{v} {one.get(k, k) if v == 1 else k}" for k, v in routine.items())
        out += ["", "<i>" + M.esc(f"Fora do sinal (180 dias): {items}") + "</i>"]
    return "\n".join(out)


BUILDERS = {"rz": sec_reasons, "rk": sec_risks, "db": sec_debate, "pr": sec_peers, "in": sec_insiders,
            "sc": sec_scenarios, "nw": sec_news}


def section(conn, callback_data: str) -> str:
    """'s|<id da classificação>|<secção>' → texto HTML. Dados de um botão antigo ou adulterado nunca dão erro."""
    parts = callback_data.split("|")
    if len(parts) != 3 or not parts[1].isdigit() or parts[2] not in BUILDERS:
        return "Este botão já não está disponível. Pede a análise outra vez."
    row = conn.execute("SELECT * FROM runs WHERE id=?", (int(parts[1]),)).fetchone()
    if not row:
        return "Análise não encontrada."
    return BUILDERS[parts[2]](report_data.from_row(conn, row))
