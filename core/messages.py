"""Mensagens do Telegram — formato compacto (escolhido pelo utilizador), em HTML.

Regras: veredicto na 1.ª linha (a negrito); factos numa linha; 2-3 pontos curtos; comando para o detalhe
(/detalhe_TICKER, /ipo_X — tocar no comando envia-o inteiro); aviso curto. Números em formato português.
Texto dinâmico é sempre escapado (HTML do Telegram).
"""
import html
import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from .ratings import IpoRating, Rating

DISCLAIMER_SHORT = "Não é aconselhamento financeiro."
LISBON = ZoneInfo("Europe/Lisbon")
_PT_SEPARATORS = str.maketrans({",": ".", ".": ","})
MINUS = "\u2212"
MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
EMOJI_RATING = {-2: "🔴", -1: "🔴", 0: "🟡", 1: "🟢", 2: "🟢"}
EMOJI_IPO = {-1: "🔴", 0: "🟡", 1: "🟢"}
EXCHANGES = [("nasdaq", "Nasdaq"), ("new york", "NYSE"), ("nyse", "NYSE"), ("tokyo", "Tóquio"), ("jpx", "Tóquio"),
             ("hong kong", "Hong Kong"), ("hkex", "Hong Kong"), ("shanghai", "Xangai"), ("star market", "Xangai STAR"),
             ("shenzhen", "Shenzhen"), ("kosdaq", "KOSDAQ"), ("kospi", "KOSPI"), ("korea", "Coreia"),
             ("london", "Londres"), ("lse", "Londres"), ("euronext", "Euronext"), ("xetra", "Xetra"),
             ("frankfurt", "Frankfurt"), ("six", "SIX"), ("deutsche", "Frankfurt")]
LEGAL = re.compile(r"[,\s]+(inc\.?|incorporated|corp\.?|corporation|pbc|ltd\.?|limited|plc|s\.a\.?|sa|n\.v\.?|nv|ag|"
                   r"co\.?|company|holdings?|group|k\.k\.?)$", re.I)


def esc(x) -> str:
    return html.escape(str(x), quote=False)


def num_pt(x: float, decimals: int = 2) -> str:
    """1234.5 → '1.234,50' (formato português: ponto nos milhares, vírgula decimal)."""
    return f"{x:,.{decimals}f}".translate(_PT_SEPARATORS)


def price_pt(x: float | None) -> str | None:
    """Preço: 2 casas até 1000, sem casas acima; ações de cêntimos com 3–4 casas (0,093 e não 0,09)."""
    if x is None:
        return None
    a = abs(x)
    if 0 < a < 1:   # até 4 casas, sem zeros a mais: 0,093 · 0,5 → 0,50
        body = num_pt(x, 4).rstrip("0")
        return body + "0" * max(0, 2 - len(body.split(",")[1]))
    return num_pt(x, 2 if round(a, 2) < 1000 else 0)


def pct_pt(x: float | None, decimals: int = 1, sign: bool = True) -> str | None:
    """+11,9% · −0,96% · 0% (nunca "-0%"); sinal de menos tipográfico."""
    if x is None:
        return None
    v = round(x, decimals)
    if v == 0:
        return "0%"
    body = num_pt(abs(v), decimals)
    if decimals and body.endswith("," + "0" * decimals):
        body = body[: -decimals - 1]
    return (MINUS if v < 0 else "+" if sign else "") + body + "%"


def when_pt(ts: str | None, with_time: bool = True) -> str | None:
    """Instante ISO (UTC) → '14 nov, 17:09' na hora de Lisboa."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return date_pt(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(LISBON)
    day = f"{dt.day} {MONTHS[dt.month - 1]}" + ("" if dt.year == datetime.now(LISBON).year else f" {dt.year}")
    return f"{day}, {dt:%H:%M}" if with_time else day


def duration_pt(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s} s" if s < 60 else f"{s // 60} min" + (f" {s % 60:02d} s" if s % 60 else "")


def big_pt(x: float | None) -> str | None:
    """916.1e9 → '916 mil M'; 1.0208e12 → '1,02 biliões'."""
    if x is None:
        return None
    a = abs(x)
    if a >= 1e12:
        return f"{num_pt(x / 1e12, 2)} biliões"
    if a >= 1e9:
        return f"{num_pt(x / 1e9, 0 if a >= 1e11 else 1)} mil M"
    if a >= 1e6:
        return f"{num_pt(x / 1e6, 0)} M"
    return num_pt(x, 0)


def range_pt(lo: float | None, hi: float | None, unit: str = "") -> str | None:
    if lo is None and hi is None:
        return None
    if lo is None or hi is None or abs(hi - lo) < 1e-9:
        return f"{big_pt(lo if lo is not None else hi)} {unit}".strip()
    return f"{big_pt(lo)}–{big_pt(hi)} {unit}".strip()


def price_range_pt(text: str | None, currency: str | None = None) -> str | None:
    """'70.00-78.00' → '70–78 USD'."""
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", str(text or "")) if float(n) > 0]
    if not nums:
        return None
    fmt = lambda v: num_pt(v, 0 if float(v).is_integer() else 2)  # noqa: E731
    body = fmt(nums[0]) if len(nums) == 1 or nums[0] == nums[1] else f"{fmt(nums[0])}–{fmt(nums[1])}"
    return f"{body} {currency or ''}".strip()


def date_pt(d: str | None) -> str | None:
    m = re.search(r"\d{4}-\d{2}-\d{2}", str(d or ""))
    if not m:
        return None
    dd = date.fromisoformat(m.group(0))
    out = f"{dd.day} {MONTHS[dd.month - 1]}"
    return out if dd.year == date.today().year else f"{out} {dd.year}"


def short_name(name: str | None) -> str:
    n = re.sub(r"\([^()]*\)", "", name or "").strip()  # sem parênteses (linear: [^()] não volta atrás)
    for _ in range(3):
        n2 = LEGAL.sub("", n).strip(" ,")
        if n2 == n:
            break
        n = n2
    if n and n.upper() == n and any(ch.isalpha() for ch in n):  # TUDO EM MAIÚSCULAS → Capitalizado (siglas curtas ficam)
        n = " ".join(w if len(w) <= 3 else w.capitalize() for w in n.split())
    return n or (name or "")


def exchange_short(ex: str | None) -> str | None:
    if not ex:
        return None
    e = ex.lower()
    for key, label in EXCHANGES:
        if key in e:
            return label
    return ex.split("(")[0].strip()[:20]


def shorten(text: str | None, n: int = 80) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(t) <= n:
        return t
    cut = t[: n - 1]
    cut = cut[: cut.rfind(" ")] if " " in cut[n // 2:] else cut
    return cut.rstrip(" ,;:.—-") + "…"


def first_clause(text: str | None) -> str:
    """Primeira oração de um parágrafo (fallback quando o agente não escreveu a versão curta)."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    m = re.split(r"(?<=[^\d])[.;:](?=\s)|\s—\s", t, maxsplit=1)
    return m[0].strip()


def point_of(reason: str | None, n: int = 80) -> str:
    """Ponto curto a partir de uma razão longa: "Fundamentais e valorização: P/E forward 2,66 e…" →
    "P/E forward 2,66 e…" (o rótulo da dimensão sozinho não diz nada)."""
    t = re.sub(r"\s+", " ", str(reason or "")).strip()
    m = re.match(r"^[^:.]{2,45}:\s+(.+)$", t)
    body = m.group(1) if m else t
    first = re.split(r"(?<=[^\d])[.;](?=\s)|\s—\s", body, maxsplit=1)[0].strip()
    return shorten(first[:1].upper() + first[1:], n)


def command_arg(symbol: str) -> str:
    """Comando tocável do Telegram só aceita [A-Za-z0-9_]: 005930.KS → 005930_KS."""
    return re.sub(r"[^A-Za-z0-9]", "_", symbol)


def footer(cmd: str | None) -> list[str]:
    return ([f"Detalhes: {cmd}"] if cmd else []) + [f"<i>{DISCLAIMER_SHORT}</i>"]


# ------------------------------------------------------------------ mensagens
def rating_change(change, s, diff: dict | None = None) -> str:
    """change: core.changes.Change · s: Synthesis · diff: {'added': [...], 'removed': [...]} (pontos curtos)."""
    head = (f"{EMOJI_RATING[int(change.new)]} <b>{esc(s.ticker)} — {esc(change.old.label.upper())} → "
            f"{esc(change.new.label.upper())}</b>")
    kind = None
    if change.kind == "confirmed":
        kind = "confirmada"
    elif abs(change.delta) >= 2:
        kind = "salto de 2+ níveis"
    price = f"{price_pt(s.price)} {s.currency or ''}".strip() if s.price is not None else None
    facts = " · ".join(x for x in (price, f"confiança {s.confidence:.0%}", kind) if x)
    points = s.key_points or [first_clause(r) for r in s.reasons[:3]]
    lines = [head, esc(facts), ""] + [f"• {esc(shorten(p, 80))}" for p in points[:3]]
    if diff and (diff.get("added") or diff.get("removed")):
        ch = [f"+ {shorten(x, 60)}" for x in diff.get("added", [])[:1]] + \
             [f"− {shorten(x, 60)}" for x in diff.get("removed", [])[:1]]
        lines += ["", "Mudou: " + esc(" / ".join(ch))]
    else:
        lines.append("")
    if s.warnings:
        lines.append("⚠️ " + esc(shorten(s.warnings[0], 80)))
    return "\n".join(lines + footer(f"/detalhe_{command_arg(s.ticker)}"))


def ipo_rating(s, rating: IpoRating, prev: IpoRating | None = None, cmd: str | None = None) -> str:
    """s: IpoSynthesis."""
    sym = f" ({esc(s.symbol)})" if s.symbol else ""
    head = f"{EMOJI_IPO[int(rating)]} <b>IPO {esc(short_name(s.name))}{sym} — {esc(rating.label.upper())}</b>"
    if prev is not None and prev != rating:
        head += f" (antes: {esc(prev.label)})"
    l2 = " · ".join(x for x in (exchange_short(s.exchange), date_pt(s.ipo_date) or "data por confirmar",
                                f"confiança {s.confidence:.0%}") if x)
    pr = price_range_pt(s.deal.price_range, s.deal.currency)
    val = range_pt(s.deal.implied_valuation_low, s.deal.implied_valuation_high, s.deal.currency or "")
    l3 = " · ".join(x for x in (f"Preço {pr}" if pr else "Preço por divulgar", f"valor {val}" if val else None) if x)
    pros = s.pros_short or [first_clause(x) for x in s.bull_case[:1]]
    cons = s.cons_short or [first_clause(x) for x in s.bear_case[:1]]
    lines = [head, esc(l2), esc(l3), ""]
    lines += [f"👍 {esc(shorten(p, 80))}" for p in pros[:2]] + [f"👎 {esc(shorten(c, 80))}" for c in cons[:2]]
    if not pr and s.not_disclosed:
        lines.append("⏳ " + esc(shorten("Por divulgar: " + ", ".join(first_clause(x) for x in s.not_disclosed[:4]), 80)))
    return "\n".join(lines + [""] + footer(cmd))


def new_ipos(items: list[dict]) -> str:
    lines = [f"🆕 <b>Novos IPOs no calendário ({len(items)})</b>"]
    for it in items[:8]:
        name = short_name(it.get("name")) + (f" ({it['symbol']})" if it.get("symbol") else "")
        size = f"{big_pt(it['value_usd'])} USD" if it.get("value_usd") else "dimensão por divulgar"
        ex = exchange_short(it.get("exchange"))
        cur = it.get("currency") or ("USD" if ex in ("Nasdaq", "NYSE") else None)  # registos antigos sem moeda
        parts = [date_pt(it.get("date")) or "data por confirmar", name, ex, price_range_pt(it.get("price_range"), cur), size]
        lines.append("• " + esc(" · ".join(p for p in parts if p)))
    if len(items) > 8:
        lines.append(f"… e mais {len(items) - 8}")
    return "\n".join(lines + [""] + footer("/ipos"))


def lockup(symbol: str, name: str, lock_date: str, days_left: int, confirmed: bool, overhang: dict) -> str:
    head = f"🔓 <b>{esc(symbol)} — fim do lock-up em {days_left} dia(s)</b> ({esc(date_pt(lock_date) or lock_date)})"
    facts = []
    if overhang.get("float_pct") is not None:
        facts.append(f"free float {num_pt(overhang['float_pct'], 0)}%")
    if overhang.get("days_to_trade_locked") is not None:
        facts.append(f"{num_pt(overhang['days_to_trade_locked'], 1)} dias de volume para absorver as ações libertadas")
    lines = [head, esc(short_name(name))] + ([esc(" · ".join(facts))] if facts else [])
    if not confirmed:
        lines.append("Prazo típico — não confirmado no prospeto.")
    return "\n".join(lines + [""] + footer(f"/detalhe_{command_arg(symbol)}"))


# ------------------------------------------------------------------ veredicto (1.ª mensagem de uma análise)
def scenario_range(forecast: dict | None, price: float | None) -> str | None:
    """'+11,9% esperado (−49% a +65%)' a partir dos cenários a 12 meses."""
    fc = forecast or {}
    exp = fc.get("expected_return_12m_pct")
    if exp is None and fc.get("expected_12m") and price:
        exp = (fc["expected_12m"] / price - 1) * 100
    if exp is None:
        return None
    out = f"{pct_pt(exp)} esperado"
    prices = [s.get("price_12m") for s in fc.get("scenarios") or [] if s.get("price_12m")]
    if price and len(prices) >= 2:
        out += f" ({pct_pt((min(prices) / price - 1) * 100, 0)} a {pct_pt((max(prices) / price - 1) * 100, 0)})"
    return out


def verdict(data: dict, *, previous: dict | None = None, change: dict | None = None, gaps: int = 0,
            total: int = 0, note: str | None = None) -> str:
    """O que se quer saber em 5 segundos: classificação e confiança, preço, porquê, o que mudou, o que esperar.

    data: report_data.by_run(...) · previous: classificação anterior da mesma ação ({rating, confidence, ts})
    change: output do nó `alert` quando houve alteração confirmada · gaps/total: passos sem dados."""
    run, p, o = data["run"], data["payload"], data["outputs"]
    prof = o.get("profile") or {}
    rating = Rating(run["rating"])
    name = shorten(short_name(prof.get("name")) or run["ticker"], 32)
    lines = [f"{EMOJI_RATING[int(rating)]} <b>{esc(name)} — {esc(rating.label.upper())}</b> · confiança "
             f"{(run['confidence'] or 0):.0%}"]
    facts = []
    if run["price"] is not None:
        cur = run["currency"] or prof.get("currency") or ""
        chg = pct_pt(prof.get("change_pct"), 2)
        facts.append(f"{price_pt(run['price'])} {cur}".strip() + (f" ({chg} hoje)" if chg else ""))
    facts.append(run["ticker"])
    lines.append(esc(" · ".join(facts)))
    if note:
        lines.append(f"<i>Pedido: {esc(shorten(note.split(';')[0], 90))}</i>")
    headline = p.get("headline") or (point_of(data["reasons"][0], 110) if data.get("reasons") else None)
    if headline:
        lines += ["", f"<i>{esc(shorten(headline, 130))}</i>"]
    extra = []
    if change and change.get("changed"):
        kind = {"confirmed": "confirmada", "immediate": "salto de 2 ou mais níveis"}.get(change.get("kind"), "")
        extra.append(f"↗️ Mudou: {esc(str(change.get('old', '')).upper())} → {esc(str(change.get('new', '')).upper())}"
                     + (f" ({kind})" if kind else ""))
    elif previous and previous.get("rating") is not None and int(previous["rating"]) != int(rating):
        old = Rating(int(previous["rating"]))
        extra.append(f"↗️ Antes: {esc(old.label.upper())} {(previous.get('confidence') or 0):.0%} "
                     f"({esc(when_pt(previous.get('ts'), False) or '')}) — a mudança ainda está por confirmar")
    elif previous and previous.get("rating") is not None:
        extra.append(f"↔️ Igual à análise anterior ({esc(when_pt(previous.get('ts'), False) or '')})")
    rng = scenario_range(o.get("forecast"), run["price"])
    if rng:
        extra.append(f"🎯 12 meses: {esc(rng)}")
    cal = o.get("calendar") or {}
    if cal.get("next_earnings"):
        days = cal.get("days_to_earnings")
        extra.append(f"📅 Resultados a {esc(date_pt(cal['next_earnings']) or '')}"
                     + (f" (daqui a {days} dias)" if isinstance(days, int) and 0 <= days <= 30 else ""))
    if gaps:
        extra.append(f"⚠️ {gaps} de {total} passos sem dados" if total else f"⚠️ {gaps} passos sem dados")
    if p.get("warnings"):
        extra.append("⚠️ " + esc(shorten(p["warnings"][0], 90)))
    if extra:
        lines += [""] + extra
    return "\n".join(lines)
