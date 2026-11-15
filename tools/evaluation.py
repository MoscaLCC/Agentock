"""Fase 7 — avaliação: backfill de retornos e relatório de acerto.

  python flow.py --backfill     # preenche ret_1d/7d/30d (+ índice do mercado) e retornos dos IPOs
  python flow.py --eval         # relatório (também gravado em data/reports/eval_<data>.md)

Acerto ("hit"), sobre o retorno em excesso a 30 dias face ao índice do mercado:
  buy/strong_buy → excesso > 0 · sell/strong_sell → excesso < 0 · hold → |excesso| ≤ 3 p.p.

Regras de medição (Fase 10, auditoria B16):
- a base da ação e a do índice são o fecho do MESMO dia (o da análise, ou a sessão seguinte se foi fora de horas);
  antes a ação partia do preço intradiário gravado e o índice do fecho, e um split posterior estragava o retorno
  (as barras vêm ajustadas a splits; o preço gravado não);
- sem retorno do índice não há excesso: a classificação fica fora das estatísticas (antes contava excesso = retorno);
- uma classificação por ação, dia e versão (a última): repetir uma análise não multiplica observações;
- o acerto direcional (compras e vendas) é mostrado à parte dos "manter", que têm um critério diferente;
- grupos com menos de 10 observações são marcados como insuficientes; a calibração compara a confiança média
  de cada escalão com o acerto observado.
"""
import json
import statistics
from datetime import date, timedelta
from pathlib import Path
from string import Template

from core import db
from core.data import DataUnavailable, get_router
from core.ratings import Rating
from core.util import BENCHMARK

HORIZONS = {"1d": 1, "7d": 7, "30d": 30}
HOLD_BAND = 3.0
MIN_GROUP = 10   # observações mínimas para um grupo dizer alguma coisa
REPORTS = Path(__file__).resolve().parent.parent / "data" / "reports"
TEMPLATE = Path(__file__).resolve().parent.parent / "agents" / "eval_agent" / "templates" / "report.md"


def close_on_or_after(bars: list[dict], d: date):
    for b in bars:
        if b.get("c") and b["t"] >= d.isoformat():
            return b["c"], b["t"]
    return None, None


def close_on_or_before(bars: list[dict], d: date):
    prev = (None, None)
    for b in bars:
        if b["t"] > d.isoformat():
            break
        if b.get("c"):
            prev = (b["c"], b["t"])
    return prev


def returns_for(bars: list[dict], start: date, base_price: float | None, today: date) -> dict:
    """Retornos a 1/7/30 dias de calendário a partir do fecho do dia `start` (ou da sessão seguinte).
    `base_price` só é usado se não houver barra nesse dia (dados em falta).
    """
    close0, day0 = close_on_or_after(bars, start)
    if close0 and day0 and date.fromisoformat(day0[:10]) - start <= timedelta(days=5):
        base, start = close0, date.fromisoformat(day0[:10])
    else:
        base = base_price or close_on_or_before(bars, start)[0]
    out = {}
    for k, h in HORIZONS.items():
        target = start + timedelta(days=h)
        if target >= today or not base:
            out[k] = None
            continue
        c, _ = close_on_or_after(bars, target)
        out[k] = round((c / base - 1) * 100, 3) if c else None
    return out


def _eod(r, symbol, start: date, today: date):
    try:
        return r.get("eod", symbol, days=(today - start).days + 10).data
    except DataUnavailable:
        return []


def backfill(conn=None, router=None, today: date | None = None) -> dict:
    conn, r, today = conn or db.connect(), router or get_router(), today or date.today()
    rows = conn.execute("SELECT * FROM runs WHERE evaluated_at IS NULL").fetchall()
    done = partial = 0
    for row in rows:
        start = date.fromisoformat(row["ts"][:10])
        ret = returns_for(_eod(r, row["ticker"], start, today), start, row["price"], today)
        bench_sym = BENCHMARK.get(row["market"] or "")
        bench = returns_for(_eod(r, bench_sym, start, today), start, None, today) if bench_sym else {}
        conn.execute("UPDATE runs SET ret_1d=?, ret_7d=?, ret_30d=?, bench_symbol=?, bench_1d=?, bench_7d=?, bench_30d=?,"
                     " evaluated_at=? WHERE id=?",
                     (ret["1d"], ret["7d"], ret["30d"], bench_sym, bench.get("1d"), bench.get("7d"), bench.get("30d"),
                      db.now() if ret["30d"] is not None else None, row["id"]))
        done += ret["30d"] is not None
        partial += ret["30d"] is None and ret["1d"] is not None
    ipo_done = backfill_ipos(conn, r, today)
    conn.commit()
    return {"runs_checked": len(rows), "runs_complete": done, "runs_partial": partial, "ipos_updated": ipo_done}


def backfill_ipos(conn, r, today: date) -> int:
    import re
    n = 0
    for row in conn.execute("SELECT * FROM ipo_ratings WHERE evaluated_at IS NULL AND symbol IS NOT NULL").fetchall():
        nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", row["price_range"] or "")]
        ipo_price = row["ipo_price"] or (sum(nums[:2]) / len(nums[:2]) if nums else None)
        if not ipo_price or not row["ipo_date"]:
            continue
        start = date.fromisoformat(row["ipo_date"][:10])
        bars = _eod(r, row["symbol"], start - timedelta(days=3), today)
        listed = [b for b in bars if b["t"] >= start.isoformat() and b.get("c")]
        if not listed:
            continue
        def ret(i):
            return round((listed[i]["c"] / ipo_price - 1) * 100, 3) if len(listed) > i else None
        d1, d30, d180 = ret(0), ret(20), ret(125)  # sessões: dia 1, ~30 dias, ~180 dias
        conn.execute("UPDATE ipo_ratings SET ipo_price=?, ret_day1=?, ret_day30=?, ret_day180=?, evaluated_at=? WHERE id=?",
                     (ipo_price, d1, d30, d180, db.now() if d180 is not None else None, row["id"]))
        n += 1
    return n


def hit(rating: int, excess: float) -> bool:
    if rating > 0:
        return excess > 0
    if rating < 0:
        return excess < 0
    return abs(excess) <= HOLD_BAND


def _bucket(rows, key):
    out = {}
    for r in rows:
        out.setdefault(key(r), []).append(r)
    return out


def _stats(rows) -> dict:
    ex = [r["excess"] for r in rows]
    return {"n": len(rows), "enough": len(rows) >= MIN_GROUP,
            "hit_rate": round(sum(r["hit"] for r in rows) / len(rows), 3) if rows else None,
            "avg_confidence": round(statistics.mean(r["confidence"] for r in rows), 3) if rows else None,
            "avg_ret_30d": round(statistics.mean(r["ret_30d"] for r in rows), 2) if rows else None,
            "avg_excess_30d": round(statistics.mean(ex), 2) if ex else None}


def build_report(conn=None) -> dict:
    conn = conn or db.connect()
    rows, seen, no_bench, repeated = [], set(), 0, 0
    for r in conn.execute("SELECT * FROM runs WHERE ret_30d IS NOT NULL ORDER BY id DESC").fetchall():
        key = (r["ticker"], (r["ts"] or "")[:10], r["version"] or "v1")
        if key in seen:           # a mesma ação analisada várias vezes no mesmo dia conta uma vez (a última)
            repeated += 1
            continue
        seen.add(key)
        if r["bench_30d"] is None:  # sem índice não há excesso: fora das estatísticas
            no_bench += 1
            continue
        excess = r["ret_30d"] - r["bench_30d"]
        rows.append({"rating": r["rating"], "confidence": r["confidence"] or 0, "market": r["market"] or "?",
                     "version": r["version"] or "v1", "ret_30d": r["ret_30d"], "excess": excess,
                     "hit": hit(r["rating"], excess)})
    total = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    conf = lambda r: "<0,5" if r["confidence"] < 0.5 else "0,5–0,7" if r["confidence"] < 0.7 else "≥0,7"  # noqa: E731
    corr = None
    if len(rows) >= 3 and len({r["rating"] for r in rows}) > 1:
        try:
            corr = round(statistics.correlation([r["rating"] for r in rows], [r["excess"] for r in rows]), 3)
        except statistics.StatisticsError:
            corr = None
    ipos = [dict(r) for r in conn.execute("SELECT name, rating, ret_day1, ret_day30, ret_day180 FROM ipo_ratings "
                                          "WHERE ret_day1 IS NOT NULL").fetchall()]
    return {
        "generated": date.today().isoformat(), "ratings_total": total, "evaluated_30d": len(rows),
        "enough_data": len(rows) >= 30, "overall": _stats(rows), "rating_vs_excess_corr": corr,
        "directional": _stats([r for r in rows if r["rating"] != 0]),   # compras e vendas, sem os "manter"
        "excluded": {"sem_indice": no_bench, "repetidas_no_dia": repeated},
        "by_rating": {Rating(k).label: _stats(v) for k, v in sorted(_bucket(rows, lambda r: r["rating"]).items())},
        "by_confidence": {k: _stats(v) for k, v in _bucket(rows, conf).items()},
        "by_market": {k: _stats(v) for k, v in _bucket(rows, lambda r: r["market"]).items()},
        "by_version": {k: _stats(v) for k, v in _bucket(rows, lambda r: r["version"]).items()},
        "ipos": ipos,
    }


def _md_table(groups: dict) -> str:
    if not groups:
        return "_sem dados_"
    lines = ["| grupo | N | acerto | confiança média | retorno 30d | excesso 30d |", "|---|---|---|---|---|---|"]
    for k, s in groups.items():
        hr = f"{s['hit_rate']:.0%}" if s["hit_rate"] is not None else "—"
        cf = f"{s['avg_confidence']:.0%}" if s.get("avg_confidence") is not None else "—"
        few = "" if s.get("enough", True) else " (N insuficiente)"
        lines.append(f"| {k}{few} | {s['n']} | {hr} | {cf} | {s['avg_ret_30d']} | {s['avg_excess_30d']} |")
    return "\n".join(lines)


def report_text(rep: dict) -> str:
    tpl = Template(TEMPLATE.read_text(encoding="utf-8"))
    warn = "" if rep["enough_data"] else (f"> ⚠ Só {rep['evaluated_30d']} classificações avaliadas a 30 dias "
                                          f"(mínimo 30): conclusões ainda não fiáveis.\n")
    ipo_lines = "\n".join(f"- {i['name']}: {i['rating']} → dia 1 {i['ret_day1']}%, dia 30 {i['ret_day30']}%, "
                          f"dia 180 {i['ret_day180']}%" for i in rep["ipos"]) or "_sem IPOs avaliados_"
    text = tpl.safe_substitute(
        generated=rep["generated"], total=rep["ratings_total"], evaluated=rep["evaluated_30d"], warning=warn,
        overall=_md_table({"todas": rep["overall"], "só compras e vendas": rep["directional"]}
                          if rep["overall"]["n"] else {}), corr=rep["rating_vs_excess_corr"],
        excluded=(f"Fora das estatísticas: {rep['excluded']['sem_indice']} sem retorno do índice, "
                  f"{rep['excluded']['repetidas_no_dia']} repetidas no mesmo dia."),
        by_rating=_md_table(rep["by_rating"]), by_confidence=_md_table(rep["by_confidence"]),
        by_market=_md_table(rep["by_market"]), by_version=_md_table(rep["by_version"]), ipos=ipo_lines,
        hold_band=HOLD_BAND)
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"eval_{rep['generated']}.md").write_text(text, encoding="utf-8")
    return text


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(backfill(), ensure_ascii=False))
    print(report_text(build_report()))
