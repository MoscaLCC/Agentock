"""Fase 9 — página HTML com o histórico de classificações de uma ação, sobre o gráfico do preço.

  python flow.py --report AAPL      → data/reports/AAPL_historico.html
"""
import html
import json
from datetime import date, timedelta
from pathlib import Path

from core import db
from core.data import DataUnavailable, get_router
from core.ratings import Rating

REPORTS = Path(__file__).resolve().parent.parent / "data" / "reports"
COLORS = {-2: "#b42318", -1: "#e5484d", 0: "#8b8d98", 1: "#30a46c", 2: "#18794e"}


def svg_chart(prices: list[tuple[str, float]], marks: list[tuple[str, float, int]], w: int = 900, h: int = 320) -> str:
    if not prices:
        return "<p>Sem preços disponíveis.</p>"
    xs = [d for d, _ in prices]
    lo = min(min(p for _, p in prices), *(m[1] for m in marks)) if marks else min(p for _, p in prices)
    hi = max(max(p for _, p in prices), *(m[1] for m in marks)) if marks else max(p for _, p in prices)
    span = (hi - lo) or 1
    pad = 40

    def x(d):
        i = xs.index(d) if d in xs else min(range(len(xs)), key=lambda k: abs(date.fromisoformat(xs[k]) - date.fromisoformat(d)))
        return pad + i * (w - 2 * pad) / max(len(xs) - 1, 1)

    def y(p):
        return h - pad - (p - lo) / span * (h - 2 * pad)

    path = " ".join(f"{'M' if i == 0 else 'L'}{x(d):.1f},{y(p):.1f}" for i, (d, p) in enumerate(prices))
    dots = "".join(
        f'<circle cx="{x(d):.1f}" cy="{y(p):.1f}" r="6" fill="{COLORS[r]}"><title>{d}: {Rating(r).label} @ {p:,.2f}</title></circle>'
        for d, p, r in marks)
    axis = (f'<text x="{pad}" y="{h - 10}" class="ax">{xs[0]}</text>'
            f'<text x="{w - pad}" y="{h - 10}" class="ax" text-anchor="end">{xs[-1]}</text>'
            f'<text x="6" y="{y(hi) + 4:.0f}" class="ax">{hi:,.2f}</text><text x="6" y="{y(lo):.0f}" class="ax">{lo:,.2f}</text>')
    return (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="preço e classificações">'
            f'<path d="{path}" fill="none" stroke="var(--line)" stroke-width="2"/>{dots}{axis}</svg>')


def build(ticker: str, conn=None) -> str:
    conn = conn or db.connect()
    t = ticker.upper()
    runs = conn.execute("SELECT * FROM runs WHERE ticker=? ORDER BY id", (t,)).fetchall()
    if not runs:
        return f"Sem classificações gravadas para {t}."
    start = date.fromisoformat(runs[0]["ts"][:10]) - timedelta(days=60)
    try:
        bars = get_router().get("eod", t, days=(date.today() - start).days + 5).data
    except DataUnavailable:
        bars = []
    prices = [(b["t"], b["c"]) for b in bars if b.get("c") and b["t"] >= start.isoformat()]
    marks = [(r["ts"][:10], r["price"], r["rating"]) for r in runs if r["price"]]
    rows = "".join(
        f"<tr><td>{r['ts'][:16].replace('T', ' ')}</td><td style='color:{COLORS[r['rating']]}'><b>{Rating(r['rating']).label}</b></td>"
        f"<td>{(r['confidence'] or 0):.0%}</td><td>{r['price'] or '—'}</td><td>{r['version'] or 'v1'}</td>"
        f"<td>{html.escape('; '.join(json.loads(r['reasons'] or '[]'))[:400])}</td></tr>" for r in reversed(runs))
    page = f"""<!doctype html><html lang="pt"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Histórico {html.escape(t)}</title><style>
:root{{--bg:#fff;--fg:#1c2024;--mut:#60646c;--line:#0d74ce;--bd:#e0e1e6}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111113;--fg:#edeef0;--mut:#b0b4ba;--line:#70b8ff;--bd:#2e3035}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0 auto;max-width:960px;padding:16px}}
svg{{width:100%;height:auto}} .ax{{fill:var(--mut);font-size:12px}} table{{border-collapse:collapse;width:100%;font-size:13px}}
td,th{{border-bottom:1px solid var(--bd);padding:6px 8px;text-align:left;vertical-align:top}} .mut{{color:var(--mut)}}
</style></head><body><h1>{html.escape(t)} — histórico de classificações</h1>
<p class="mut">{len(runs)} classificações · pontos coloridos = classificação na data (verde compra, cinzento hold, vermelho venda)</p>
{svg_chart(prices, marks)}
<table><thead><tr><th>data (UTC)</th><th>classificação</th><th>confiança</th><th>preço</th><th>versão</th><th>razões</th></tr></thead>
<tbody>{rows}</tbody></table>
<p class="mut">Análise automática do Agentock — não é aconselhamento financeiro.</p></body></html>"""
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"{t.replace('.', '_')}_historico.html"
    out.write_text(page, encoding="utf-8")
    return str(out)
