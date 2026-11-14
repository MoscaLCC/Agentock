"""Fase 8 — correr o fluxo para o universo (chamado pelo flow.py).

  python flow.py --universe --top 20                 # mostra o universo e a estimativa de custo/tempo
  python flow.py --universe --top 20 --yes           # corre
  python flow.py --universe --top 20 --yes --parallel 2 --resume   # retoma o último lote, 2 ações em paralelo
"""
import asyncio
import uuid
from datetime import datetime, timezone

from core import db
from core.runner import run_agent

DEFAULT_COST = 3.0  # USD por ação quando ainda não há histórico de execuções completas


def estimate(conn, n: int, parallel: int) -> dict:
    rows = conn.execute(
        "SELECT run_id, SUM(COALESCE(cost_usd,0)) AS cost, MIN(ts) AS t0, MAX(ts) AS t1 FROM agent_outputs "
        "WHERE run_id IN (SELECT run_id FROM agent_outputs WHERE node='guard' AND status='ok') GROUP BY run_id"
    ).fetchall()
    costs = [r["cost"] for r in rows if r["cost"]]
    secs = []
    for r in rows:
        try:
            secs.append((datetime.fromisoformat(r["t1"]) - datetime.fromisoformat(r["t0"])).total_seconds() + 60)
        except (TypeError, ValueError):
            pass
    per = sum(costs) / len(costs) if costs else DEFAULT_COST
    per_s = sum(secs) / len(secs) if secs else 600
    return {"samples": len(costs), "per_ticker_usd": round(per, 2), "total_usd": round(per * n, 2),
            "hours": round(per_s * n / max(parallel, 1) / 3600, 1)}


async def main(a, params: dict, run_ticker) -> None:
    res = await run_agent("universe_agent", {"top_n": a.top, "refresh": a.refresh})
    if res.status != "ok":
        print(f"universe_agent falhou: {res.error}")
        return
    uni = res.output["universe"]
    print(f"Universo: {len(uni)} ações (corte {uni[-1]['market_cap_usd'] / 1e9:.0f} mil M USD) · "
          f"acrescentadas: {res.output.get('injected')} · referência em falta: {res.output.get('missing_reference')}")
    for u in uni[:10]:
        print(f"  {u['rank']:3} {u['symbol']:12} {u['market_cap_usd'] / 1e9:8.0f} mil M USD  {u['name']}")
    conn = db.connect()
    est = estimate(conn, len(uni), a.parallel)
    basis = f"média de {est['samples']} execuções completas" if est["samples"] else "sem histórico: estimativa por omissão"
    print(f"\nCusto estimado: ~{est['total_usd']} USD ({est['per_ticker_usd']} USD/ação, {basis}); "
          f"tempo ~{est['hours']} h com --parallel {a.parallel}.")
    if not a.yes:
        print("Para correr, repete com --yes.")
        return

    if a.resume:
        row = conn.execute("SELECT batch_id FROM universe_progress ORDER BY ts DESC LIMIT 1").fetchone()
        batch = row["batch_id"] if row else None
    else:
        batch = None
    batch = batch or f"u{datetime.now(timezone.utc):%Y%m%d%H%M}-{uuid.uuid4().hex[:4]}"
    done = {r["ticker"] for r in conn.execute(
        "SELECT ticker FROM universe_progress WHERE batch_id=? AND status='ok'", (batch,)).fetchall()}
    print(f"Lote {batch}: {len(done)} já concluídas, {len(uni) - len(done)} por fazer.")
    sem = asyncio.Semaphore(max(a.parallel, 1))

    async def one(u):
        sym = u["symbol"]
        if sym in done:
            return
        async with sem:
            try:
                rep = await run_ticker(sym, a, params)
                g = rep.results.get("guard")
                status, run_id = ("ok" if g and g.status == "ok" else "failed"), rep.run_id
            except Exception as e:  # uma ação falhada não pára o lote
                status, run_id = f"error: {type(e).__name__}", None
            conn.execute("INSERT OR REPLACE INTO universe_progress VALUES (?,?,?,?,?)",
                         (batch, sym, status, run_id, db.now()))
            conn.commit()

    await asyncio.gather(*(one(u) for u in uni))
    stats = conn.execute("SELECT status, COUNT(*) n FROM universe_progress WHERE batch_id=? GROUP BY status",
                         (batch,)).fetchall()
    print("Lote concluído:", {r["status"]: r["n"] for r in stats})
