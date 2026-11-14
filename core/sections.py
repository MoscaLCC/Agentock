"""Cartão (imagem + legenda + botões) e secções a pedido para o Telegram.

Princípio: pouco texto à primeira vista (o cartão), detalhe só quando se toca num botão; tabelas em <pre>
(monoespaçado, ≤ 36 colunas para caber no telemóvel).
"""
import re

from . import charts, messages as M, report_data
from .data import DataUnavailable, get_router
from .ratings import Rating
from .telegram import keyboard

SECTIONS = [("rz", "🧾 Razões"), ("rk", "⚠️ Riscos"), ("db", "🥊 Debate"),
            ("pr", "🏢 Peers"), ("sc", "🎯 Cenários"), ("nw", "📰 Notícias")]


def buttons(row_id: int) -> dict:
    cb = [(label, f"s|{row_id}|{key}") for key, label in SECTIONS]
    return keyboard([cb[:3], cb[3:]])


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
    lines = [f"{M.EMOJI_RATING[int(rating)]} <b>{M.esc(run['ticker'])} — {M.esc(rating.label.upper())}</b>"]
    if note:
        lines.append(f"<i>Pedido: {M.esc(M.shorten(note.split(';')[0], 90))}</i>")
    if p.get("headline"):
        lines += ["", f"<i>{M.esc(p['headline'])}</i>"]
    points = p.get("key_points") or [M.first_clause(r) for r in data["reasons"][:3]]
    lines += [""] + [f"• {M.esc(M.shorten(x, 80))}" for x in points[:3]]
    lines += ["", "Toca nos botões para ver o detalhe.", f"<i>{M.DISCLAIMER_SHORT}</i>"]
    return "\n".join(lines)


# ------------------------------------------------------------------ secções
def _bold_prefix(text: str) -> str:
    m = re.match(r"^([^:]{2,40}):\s*(.+)$", text, re.S)
    return f"<b>{M.esc(m.group(1))}</b>: {M.esc(m.group(2))}" if m else M.esc(text)


def _title(data: dict, name: str) -> str:
    return f"<b>{name}</b> · {M.esc(data['run']['ticker'])}"


def sec_reasons(data: dict) -> str:
    return "\n".join([_title(data, "Razões"), ""] +
                     [f"{i}. {_bold_prefix(r)}" for i, r in enumerate(data["reasons"], 1)])


def sec_risks(data: dict) -> str:
    risks = data["payload"].get("risks") or []
    body = [f"• {_bold_prefix(r)}" for r in risks] or ["Sem riscos registados."]
    gaps = data["payload"].get("data_gaps") or []
    if gaps:
        body += ["", M.esc("Sem dados nesta análise: " + ", ".join(gaps))]
    return "\n".join([_title(data, "Riscos"), ""] + body)


def sec_debate(data: dict) -> str:
    d = data["payload"].get("debate") or {}
    if not (d.get("bull") or d.get("bear")):
        return _title(data, "Debate") + "\n\nEsta análise não teve debate (classificação v1)."
    return "\n".join([_title(data, "Debate"), "", f"👍 <b>A favor</b>\n{M.esc(d.get('bull') or '—')}", "",
                      f"👎 <b>Contra</b>\n{M.esc(d.get('bear') or '—')}"])


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
        return _title(data, "Peers") + "\n\nSem tabela de comparáveis nesta análise."
    head = f"{'':10}{'P/E':>6}{'EV/EB':>6}{'M.op':>6}{'12m':>7}"
    lines = [head]
    for i, r in enumerate(rows[:8]):
        name = (r["symbol"] + ("*" if i == 0 and comps.get("target") else ""))[:10]
        lines.append(f"{name:10}{_cell(r.get('forward_pe') or r.get('trailing_pe'))}{_cell(r.get('ev_to_ebitda'))}"
                     f"{_cell(r.get('operating_margin'), 0, '%')}{_cell(r.get('ret_12m_pct'), 0, '%', True, 7)}")
    med = comps.get("medians") or {}
    lines.append(f"{'mediana':10}{_cell(med.get('forward_pe') or med.get('trailing_pe'))}{_cell(med.get('ev_to_ebitda'))}"
                 f"{_cell(med.get('operating_margin'), 0, '%')}{_cell(med.get('ret_12m_pct'), 0, '%', True, 7)}")
    legend = "P/E dos próximos 12 meses · EV/EBITDA · margem operacional · retorno a 12 meses. * = esta empresa"
    return "\n".join([_title(data, "Peers"), f"<pre>{M.esc(chr(10).join(lines))}</pre>", f"<i>{legend}</i>"])


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
    if fc.get("summary"):
        out += ["", f"<i>{M.esc(M.shorten(fc['summary'], 300))}</i>"]
    return "\n".join(out)


def sec_news(data: dict) -> str:
    o, seen, items = data["outputs"], set(), []
    for node in ("news_4h", "news_24h", "news_7d", "news_30d"):
        for it in (o.get(node) or {}).get("items") or []:
            key = (it.get("url") or it.get("title") or "").split("?")[0]
            if key and key not in seen:
                seen.add(key)
                items.append(it)
    if not items:
        return _title(data, "Notícias") + "\n\nSem notícias nesta análise."
    items.sort(key=lambda i: i.get("published_at") or "", reverse=True)   # mais recentes primeiro…
    items.sort(key=lambda i: -(i.get("relevance") or 0))                  # …dentro da mesma relevância (estável)
    tone = {"positivo": "🟢", "negativo": "🔴"}
    lines = [_title(data, "Notícias"), ""]
    for it in items[:6]:
        when = M.date_pt(it.get("published_at")) or ""
        lines.append(f"{tone.get(it.get('tone'), '⚪')} <a href=\"{M.esc(it.get('url'))}\">{M.esc(M.shorten(it['title'], 90))}</a>"
                     f" — {M.esc(it.get('source') or '')} · {M.esc(when)}")
    return "\n".join(lines)


BUILDERS = {"rz": sec_reasons, "rk": sec_risks, "db": sec_debate, "pr": sec_peers, "sc": sec_scenarios, "nw": sec_news}


def section(conn, callback_data: str) -> str:
    """'s|<id da classificação>|<secção>' → texto HTML."""
    _s, row_id, key = callback_data.split("|")
    row = conn.execute("SELECT * FROM runs WHERE id=?", (int(row_id),)).fetchone()
    if not row:
        return "Análise não encontrada."
    return BUILDERS[key](report_data.from_row(conn, row))
