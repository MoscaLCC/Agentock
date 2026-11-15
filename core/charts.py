"""Cartão visual de uma análise (PNG para o Telegram).

Paleta e regras: skill dataviz (references/palette.md). Modo escuro por omissão (AGENTOCK_CHART_THEME=light para claro).
- linhas finas (2 px preço, 1,5 px médias), grelha horizontal em hairline sólido, legenda com ≥ 2 séries
- scores: barras divergentes azul (+) / vermelho (−) com o valor escrito (a cor nunca é a única pista)
- classificação: cor de estado + rótulo escrito
- números em formato português; texto sempre com tinta de texto, nunca com a cor da série
"""
import io
import math
import os
from datetime import date

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from .messages import MONTHS, date_pt, num_pt, price_pt, short_name, shorten, when_pt  # noqa: E402
from .ratings import Rating  # noqa: E402

THEMES = {
    "dark": {"surface": "#1a1a19", "ink": "#f0efec", "ink2": "#c3c2b7", "muted": "#898781", "grid": "#2c2c2a",
             "axis": "#383835", "s1": "#3987e5", "s2": "#d95926", "s3": "#199e70", "pos": "#3987e5",
             "neg": "#e66767", "band": "#3987e5"},
    "light": {"surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781", "grid": "#e1e0d9",
              "axis": "#c3c2b7", "s1": "#2a78d6", "s2": "#eb6834", "s3": "#1baf7a", "pos": "#2a78d6",
              "neg": "#e34948", "band": "#2a78d6"},
}
STATUS = {"good": "#0ca30c", "critical": "#d03b3b", "neutral": "#6f6e69"}
FONT = ["Segoe UI", "DejaVu Sans", "Arial", "sans-serif"]


def theme() -> dict:
    return THEMES.get(os.environ.get("AGENTOCK_CHART_THEME", "dark"), THEMES["dark"])


def _pt_axis(v, _pos=None):
    if v == 0:
        return "0"
    a = abs(v)  # ações de cêntimos: com 2 casas o eixo mostrava "0,00" cinco vezes
    return num_pt(v, 0 if a >= 100 else 1 if a >= 10 else 2 if a >= 1 else 3 if a >= 0.1 else 4)


def _sma(values: list[float], n: int) -> list[float | None]:
    out, acc = [], 0.0
    for i, v in enumerate(values):
        acc += v
        if i >= n:
            acc -= values[i - n]
        out.append(acc / n if i >= n - 1 else None)
    return out


def _style_axis(ax, t):
    ax.set_facecolor(t["surface"])
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(t["axis"])
    ax.tick_params(colors=t["muted"], labelsize=7.5, length=0)
    ax.grid(axis="y", color=t["grid"], linewidth=0.6)
    ax.set_axisbelow(True)


def _rating_color(r: Rating) -> str:
    return STATUS["good"] if int(r) > 0 else STATUS["critical"] if int(r) < 0 else STATUS["neutral"]


def place_labels(items: list[tuple[float, str]], x0: float, x1: float, levels: list[float],
                 char_frac: float = 0.0105, gap: float = 0.015) -> list[float]:
    """Nível vertical para cada etiqueta (x, texto) sem sobreposição: mede a largura do texto em fração do eixo
    e escolhe o primeiro nível livre. items devem vir ordenados por x."""
    span = (x1 - x0) or 1
    occupied: dict[float, list[tuple[float, float]]] = {lv: [] for lv in levels}
    out = []
    for x, text in items:
        c = (x - x0) / span
        half = len(text) * char_frac / 2
        a, b = max(0.0, c - half), min(1.0, c + half)
        chosen = levels[-1]
        for lv in levels:
            if all(b + gap <= s or a - gap >= e for s, e in occupied[lv]):
                chosen = lv
                break
        occupied[chosen].append((a, b))
        out.append(chosen)
    return out


W_IN, H_IN = 6.0, 9.1  # medidas de desenho (polegadas): as posições abaixo referem-se a estas
# A figura é criada mais pequena e com mais pontos por polegada: os mesmos 1080 × 1638 px, mas a letra (em pontos)
# fica ~18% maior em relação ao desenho — na bolha do chat do telemóvel a de 6,5 pt não se lia.
SCALE = 0.85


def _y(inches_from_top: float) -> float:
    return 1 - inches_from_top / H_IN


def _box(left: float, top_in: float, width: float, height_in: float) -> list[float]:
    """Retângulo de eixos com topo e altura em polegadas (layout previsível)."""
    return [left, _y(top_in + height_in), width, height_in / H_IN]


def stock_card(data: dict, bars: list[dict]) -> bytes:
    """data: report_data.latest(...) · bars: preços diários (≥ 200 sessões para a média de 200 dias)."""
    t = theme()
    o, run = data["outputs"], data["run"]
    prof, ind = o.get("profile") or {}, o.get("indicators") or {}
    rating = Rating(run["rating"])
    plt.rcParams["font.family"] = FONT
    fig = plt.figure(figsize=(W_IN * SCALE, H_IN * SCALE), dpi=180 / SCALE, facecolor=t["surface"])

    # ---------------------------------------------------------------- cabeçalho
    title = shorten(short_name(prof.get("name")) or run["ticker"], 19)   # o nome diz mais do que o código
    fig.text(0.05, _y(0.30), title, fontsize=16, fontweight="bold", color=t["ink"], va="center")
    cur = run["currency"] or prof.get("currency") or ""
    chg = prof.get("change_pct")
    sub = f"{run['ticker']} · {price_pt(run['price'])} {cur}" if run["price"] else run["ticker"]
    if chg is not None:
        sub += f" ({'+' if chg >= 0 else ''}{num_pt(chg, 2)}%)"
    fig.text(0.05, _y(0.60), sub, fontsize=9, color=t["ink2"], va="center")
    fig.patches.append(FancyBboxPatch((0.66, _y(0.47)), 0.29, 0.33 / H_IN,
                                      boxstyle="round,pad=0.004,rounding_size=0.012", transform=fig.transFigure,
                                      facecolor=_rating_color(rating), edgecolor="none"))
    fig.text(0.805, _y(0.305), rating.label.upper(), fontsize=11, fontweight="bold", color="#ffffff",
             ha="center", va="center")
    fig.text(0.95, _y(0.60), f"confiança {(run['confidence'] or 0):.0%} · {run['version'] or 'v1'}", fontsize=8.5,
             color=t["ink2"], ha="right", va="center")

    # ---------------------------------------------------------------- 1) preço 6 meses + médias + níveis
    ax = fig.add_axes(_box(0.13, 1.15, 0.79, 2.05))
    _style_axis(ax, t)
    closes = [b["c"] for b in bars if b.get("c")]
    dates = [date.fromisoformat(b["t"][:10]) for b in bars if b.get("c")]
    if closes:
        s50, s200 = _sma(closes, 50), _sma(closes, 200)
        k = max(0, len(closes) - 126)
        d, c = dates[k:], closes[k:]
        months = max(1, round((d[-1] - d[0]).days / 30.4))  # ação recente: o título diz o que o gráfico mostra
        fig.text(0.05, _y(0.95), f"Preço · {months} {'mês' if months == 1 else 'meses'}", fontsize=9,
                 color=t["muted"], va="center")
        ax.plot(d, c, color=t["s1"], linewidth=2, label="Preço", solid_capstyle="round")
        for series, color, name in ((s50, t["s2"], "Média 50 dias"), (s200, t["s3"], "Média 200 dias")):
            seg = series[k:]
            if any(v is not None for v in seg):
                ax.plot(d, [v if v is not None else math.nan for v in seg], color=color, linewidth=1.5, label=name)
        lv = ind.get("levels") or {}
        lo, hi = min(c), max(c)
        for val, tag in [(v, "suporte") for v in (lv.get("supports") or [])[:2]] + \
                        [(v, "resistência") for v in (lv.get("resistances") or [])[:1]]:
            if lo * 0.85 <= val <= hi * 1.15:  # níveis são limiares: tracejado fino, não grelha
                ax.axhline(val, color=t["muted"], linewidth=0.8, linestyle=(0, (3, 3)), zorder=1)
                ax.text(d[0], val, f"{tag} {_pt_axis(val)}", color=t["muted"], fontsize=6.5, va="center",
                        bbox={"facecolor": t["surface"], "edgecolor": "none", "pad": 1.2}, zorder=4)
        ax.annotate(_pt_axis(c[-1]), (d[-1], c[-1]), xytext=(4, 0), textcoords="offset points", color=t["ink"],
                    fontsize=8, fontweight="bold", va="center")
        ax.yaxis.set_major_formatter(FuncFormatter(_pt_axis))
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _p: MONTHS[mdates.num2date(v).month - 1]))
        leg = ax.legend(loc="lower right", bbox_to_anchor=(1.0, 1.0), fontsize=7, frameon=False,
                        labelcolor=t["ink2"], handlelength=1.4, ncol=3, borderaxespad=0.2)  # fora do gráfico
        for line in leg.get_lines():
            line.set_linewidth(2)
        ax.set_xlim(d[0], d[-1])
    else:
        fig.text(0.05, _y(0.95), "Preço", fontsize=9, color=t["muted"], va="center")
        ax.set_xticks([])
        ax.set_yticks([])
        ax.text(0.5, 0.5, "sem preços", transform=ax.transAxes, ha="center", color=t["muted"])

    # ---------------------------------------------------------------- 2) preço vs alvos e cenários (régua de preço)
    pt, fc = o.get("price_targets") or {}, o.get("forecast") or {}
    fig.text(0.05, _y(3.72), "Preço vs. alvos dos analistas (faixa: mín–máx) e cenários a 12 meses", fontsize=9,
             color=t["muted"], va="center")
    ax2 = fig.add_axes(_box(0.07, 3.90, 0.86, 1.00))
    ax2.set_facecolor(t["surface"])
    for s in ("top", "right", "left"):
        ax2.spines[s].set_visible(False)
    ax2.spines["bottom"].set_color(t["axis"])
    ax2.set_yticks([])
    ax2.tick_params(colors=t["muted"], labelsize=7, length=0)
    marks = []  # (x, rótulo, cor, marcador)
    price = run["price"]
    if price:
        marks.append((price, "preço", t["ink"], "o"))
    if pt.get("mean"):
        marks.append((pt["mean"], "alvo médio", t["s1"], "D"))
    for sc in fc.get("scenarios") or []:
        nm = {"bear": "pessimista", "base": "base", "bull": "otimista"}.get(sc["name"], sc["name"])
        col = t["neg"] if sc["name"] == "bear" else t["pos"] if sc["name"] == "bull" else t["ink2"]
        marks.append((sc["price_12m"], f"{nm} {sc['probability']:.0%}", col, "v" if sc["name"] == "bear" else "^"
                      if sc["name"] == "bull" else "s"))
    xs = [m[0] for m in marks] + [v for v in (pt.get("low"), pt.get("high")) if v]
    if xs:
        lo, hi = min(xs), max(xs)
        pad = (hi - lo) * 0.10 or hi * 0.05
        x0, x1 = lo - pad, hi + pad
        ax2.set_xlim(x0, x1)
        ax2.set_ylim(-2.2, 2.2)
        if pt.get("low") and pt.get("high"):
            ax2.fill_between([pt["low"], pt["high"]], -0.22, 0.22, color=t["band"], alpha=0.28, linewidth=0)
        ax2.axhline(0, color=t["axis"], linewidth=0.8, zorder=1)
        marks.sort(key=lambda m: m[0])
        texts = [f"{label} · {_pt_axis(x)}" for x, label, _c, _m in marks]
        levels = place_labels([(m[0], tx) for m, tx in zip(marks, texts)], x0, x1, [1.0, 1.75, -1.15, -1.85])
        for (x, label, col, mk), tx, lv in zip(marks, texts, levels):
            is_price = label == "preço"  # o preço fica por cima dos cenários próximos
            ax2.plot([x, x], [0, lv * 0.82], color=t["grid"], linewidth=0.8, zorder=1)  # fio até à etiqueta
            ax2.plot([x], [0], marker=mk, markersize=9 if is_price else 8, color=col, markeredgecolor=t["surface"],
                     markeredgewidth=1.5, linestyle="none", zorder=5 if is_price else 3)
            ax2.text(x, lv, tx, fontsize=6.5, color=t["ink2"], ha="center", va="center",
                     bbox={"facecolor": t["surface"], "edgecolor": "none", "pad": 0.8}, zorder=4)
        ax2.xaxis.set_major_formatter(FuncFormatter(_pt_axis))
        ax2.xaxis.set_major_locator(plt.MaxNLocator(5))
    else:
        ax2.text(0.5, 0.5, "sem alvos nem cenários", transform=ax2.transAxes, ha="center", color=t["muted"])
        ax2.set_xticks([])

    # ---------------------------------------------------------------- 3) scores por dimensão (−2 a +2)
    def g(node, key):
        v = (o.get(node) or {}).get(key)
        return float(v) if isinstance(v, (int, float)) else None

    def scale100(v):
        return None if v is None else max(-2.0, min(2.0, (v - 50) / 25))

    dims = [("Técnica", g("technical", "score")), ("Fundamental", g("fundamental", "score")),
            ("Sentimento", g("sentiment", "score")), ("Timing", g("timing", "score")),
            ("Analistas", g("analysts", "consensus_score")), ("Insiders", g("insiders", "score")),
            ("Saúde financeira", scale100(g("health", "health_score"))),
            ("Momentum", scale100(g("health", "momentum_score")))]
    fig.text(0.05, _y(5.40), "Scores por dimensão  (−2 negativo · +2 positivo)", fontsize=9, color=t["muted"],
             va="center")
    sc_top, sc_h = 5.58, 1.80
    ax3 = fig.add_axes(_box(0.33, sc_top, 0.6, sc_h))
    ax3.set_facecolor(t["surface"])
    for s in ("top", "right", "left", "bottom"):
        ax3.spines[s].set_visible(False)
    ys = list(range(len(dims)))[::-1]
    for y, (name, v) in zip(ys, dims):
        frac = (y + 0.6) / (len(dims) + 0.2)  # mesma escala do ylim (-0.6 … n-0.4)
        fig.text(0.31, _y(sc_top + sc_h) + frac * sc_h / H_IN, name, fontsize=8.5, color=t["ink2"], ha="right",
                 va="center")
        if v is None:
            ax3.text(0, y, "sem dados", fontsize=7, color=t["muted"], ha="center", va="center")
            continue
        v = max(-2.0, min(2.0, v))
        ax3.barh(y, v, height=0.56, color=t["pos"] if v >= 0 else t["neg"], edgecolor="none")
        txt = f"{'+' if v > 0 else ''}{num_pt(v, 1)}"
        ax3.text(v + (0.08 if v >= 0 else -0.08), y, txt, fontsize=7.5, color=t["ink"],
                 ha="left" if v >= 0 else "right", va="center")
    ax3.axvline(0, color=t["axis"], linewidth=1)
    ax3.set_xlim(-2.4, 2.4)
    ax3.set_ylim(-0.6, len(dims) - 0.4)
    ax3.set_yticks([])
    ax3.set_xticks([-2, -1, 0, 1, 2])
    ax3.xaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{'+' if v > 0 else ''}{int(v)}"))
    ax3.tick_params(colors=t["muted"], labelsize=7, length=0)
    ax3.grid(axis="x", color=t["grid"], linewidth=0.6)
    ax3.set_axisbelow(True)

    # ---------------------------------------------------------------- 4) números-chave
    fd, cal, an = o.get("fundamental_data") or {}, o.get("calendar") or {}, o.get("analysts") or {}
    val, bal = fd.get("valuation") or {}, fd.get("balance") or {}

    def f(v, suffix="", nd=1):
        return "—" if v is None else f"{num_pt(v, nd)}{suffix}"

    cells = [("P/E (próx. 12m)", f(val.get("forward_pe"))), ("EV/EBITDA", f(val.get("ev_to_ebitda"))),
             ("Dividendo", f(val.get("dividend_yield_pct"), "%")), ("ROE", f(bal.get("roe_pct"), "%", 0)),
             ("Potencial (alvo médio)", f(pt.get("upside_mean_pct"), "%")),
             ("Volatilidade anual", f(ind.get("volatility_ann_pct"), "%", 0)),
             ("Analistas", f"{an.get('consensus_label') or '—'} ({an.get('n_analysts') or 0})"),
             ("Próximos resultados", date_pt(cal.get("next_earnings")) or "—")]
    fig.text(0.05, _y(7.82), "Números-chave", fontsize=9, color=t["muted"], va="center")
    for i, (label, value) in enumerate(cells):
        col, row = i % 4, i // 4
        x, top = 0.05 + col * 0.235, 8.10 + row * 0.47
        fig.text(x, _y(top), value, fontsize=10.5, color=t["ink"], fontweight="bold", va="center")
        fig.text(x, _y(top + 0.18), label, fontsize=6.5, color=t["muted"], va="center")

    stamp = when_pt(run["ts"]) or ""
    fig.text(0.05, _y(8.98), f"Agentock · {stamp} (Lisboa) · análise automática, não é aconselhamento financeiro",
             fontsize=6, color=t["muted"], va="center")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=t["surface"])
    plt.close(fig)
    return buf.getvalue()
