"""Reexecuta UM nó de uma análise gravada, com os mesmos dados, para comparar antes/depois (A/B).

  python tools/replay.py RUN_ID NÓ                    # ex.: 20261114T225146-coupang-d7df77 timing
  python tools/replay.py RUN_ID NÓ --model claude-sonnet-5-5   # mesmo input, outro modelo
  python tools/replay.py RUN_ID NÓ --agent rating_v1_agent     # mesmo input, outro agente
  python tools/replay.py RUN_ID rating --chain        # debate completo: dossier → bull ∥ bear → rating → guard

Os inputs são reconstruídos a partir dos outputs gravados dos nós a montante (tabela agent_outputs). Os nós de
código que não existiam na execução gravada (news, sentiment, dossier) são recalculados a partir dos dados dela.
O resultado vai para data/replay.db (não toca no histórico nem nas medições de data/agentock.db) e não usa cache.
Atenção: um nó LLM gasta utilização da subscrição (o custo equivalente aparece no fim).
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import core.env  # noqa: E402,F401
from core import db, dossier, news, sentiment, spec as spec_mod  # noqa: E402
from core.orchestrator import deps, flow_defaults, layers, load_flow, resolve  # noqa: E402
from core.runner import AgentResult, run_agent, to_jsonable  # noqa: E402

REPLAY_DB = ROOT / "data" / "replay.db"


def recorded(conn, run_id: str) -> dict[str, dict]:
    rows = conn.execute("SELECT * FROM agent_outputs WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
    return {r["node"]: dict(r) for r in rows}


def recorded_results(conn, run_id: str) -> dict[str, AgentResult]:
    """Outputs gravados + os nós de código da Fase 10 recalculados com esses dados (execuções antigas não os têm)."""
    res = {n: AgentResult(r["agent"], r["status"], json.loads(r["output"]) if r["output"] else None)
           for n, r in recorded(conn, run_id).items()}

    def out(n):
        r = res.get(n)
        return r.output if r is not None and r.status == "ok" else None

    if "news" not in res and any(f"news_{w}" in res for w, _ in news.WINDOWS):
        res["news"] = AgentResult("news_agent", "ok", news.legacy_digest({w: out(f"news_{w}") for w, _ in news.WINDOWS}))
        if res["news"].output is None:
            res["news"] = AgentResult("news_agent", "failed")
        # o sentimento passou a código: recalcula-o com as notícias fundidas (os insiders não existiam antes do 2.20)
        res["sentiment"] = AgentResult("sentiment_agent", "ok", sentiment.compute(out("news"), out("analysts"), out("insiders")))
    if "insiders" not in res:  # execuções anteriores ao insiders_agent: não é uma lacuna nova, é "sem fonte"
        res["insiders"] = AgentResult("insiders_agent", "ok", {"available": False, "score": None,
                                      "reason": "não analisado nesta execução (anterior ao agente de insiders)"})
    if "dossier" not in res and "profile" in res:
        res["dossier"] = AgentResult("dossier_agent", "ok", dossier.build({k: out(k) for k in dossier.SECTIONS}))
    return res


def node_inputs(results: dict, run_id: str, node: str, flow: str = "ticker", params: dict | None = None) -> tuple[str, dict]:
    """(agente, inputs) do nó tal como o orquestrador os resolveria."""
    nodes = load_flow(flow)
    if node not in nodes:
        raise ValueError(f"nó desconhecido: {node}")
    prof = (results["profile"].output or {}) if results.get("profile") else {}
    params = {**flow_defaults(flow), "ticker": prof.get("symbol"), "run_id": run_id, **(params or {})}
    return resolve(nodes[node].agent, params, results), resolve(nodes[node].inputs, params, results)


def tokens(usage: dict | None) -> dict:
    keys = ("input", "cache_write", "cache_read", "output")
    return {k: sum(u.get(k, 0) for u in (usage or {}).values()) for k in keys}


def _with_model(name: str, model: str | None):
    if not model:
        return
    original = spec_mod.load_agent

    def patched(n, agents_dir=None):
        s = original(n, agents_dir)
        if n == name:
            s.model = model
        return s
    import core.runner as runner
    runner.load_agent = patched


async def replay(run_id: str, node: str, *, agent: str | None = None, model: str | None = None,
                 flow: str = "ticker", chain: bool = False, params: dict | None = None) -> dict:
    """chain=True: corre também os nós a montante que a execução gravada não tem (ex.: bull e bear), por ordem."""
    src = db.connect()
    rec = recorded(src, run_id)
    results = recorded_results(src, run_id)
    nodes = load_flow(flow)
    todo = [node]
    if chain:
        order = [n for layer in layers(nodes) for n in layer]
        need, stack = set(), [node]
        while stack:
            n = stack.pop()
            for d in deps(nodes[n], nodes):
                if d not in results and d not in need:
                    need.add(d)
                    stack.append(d)
        todo = [n for n in order if n in need] + [node]
        if "guard" in nodes and node == "rating":
            todo.append("guard")
    out_db = db.connect(REPLAY_DB)
    rid = f"replay-{run_id[-6:]}-{node}"
    steps, last = [], None

    async def one(n: str) -> AgentResult:
        name, inputs = node_inputs(results, run_id, n, flow, params)
        if n == node:
            name = agent or name
            _with_model(name, model)
        return await run_agent(name, inputs, run_id=rid, node=n, use_cache=False, conn=out_db,
                               timeout=nodes[n].timeout)

    i = 0
    while i < len(todo):
        batch = [todo[i]]
        while i + len(batch) < len(todo) and not (deps(nodes[todo[i + len(batch)]], nodes) & set(batch)) \
                and not any(todo[i + len(batch)] in deps(nodes[b], nodes) for b in batch):
            batch.append(todo[i + len(batch)])       # nós independentes (bull e bear) correm em paralelo
        outs = await asyncio.gather(*(one(n) for n in batch))
        for n, res in zip(batch, outs):
            results[n] = res
            steps.append({"node": n, "agent": res.agent, "status": res.status, "error": res.error,
                          "cost_usd": res.cost_usd or 0, "duration_s": (res.duration_ms or 0) / 1000,
                          "turns": res.turns, "tokens": tokens(res.usage), "output": to_jsonable(res.output)})
            if n == node:
                last = steps[-1]
        i += len(batch)
    r = rec.get(node)
    return {"node": node, "steps": steps, "after": last,
            "before": None if not r else {"cost_usd": r["cost_usd"], "duration_s": (r["duration_ms"] or 0) / 1000,
                                          "turns": r["turns"], "output": json.loads(r["output"] or "null")}}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("run_id")
    p.add_argument("node")
    p.add_argument("--agent")
    p.add_argument("--model")
    p.add_argument("--flow", default="ticker")
    p.add_argument("--chain", action="store_true", help="corre também os nós a montante que faltam na execução gravada")
    p.add_argument("--quiet", action="store_true", help="não imprime os outputs completos")
    a = p.parse_args()
    out = asyncio.run(replay(a.run_id, a.node, agent=a.agent, model=a.model, flow=a.flow, chain=a.chain))
    b = out["before"] or {}
    print(f"antes : {a.node}: {b.get('cost_usd') or 0:.4f} USD · {b.get('duration_s') or 0:.1f} s · {b.get('turns')} turnos")
    for s in out["steps"]:
        print(f"depois: {s['node']} ({s['agent']}{', ' + a.model if a.model and s['node'] == a.node else ''}): {s['status']} "
              f"{s['error'] or ''} · {s['cost_usd']:.4f} USD · {s['duration_s']:.1f} s · {s['turns']} turnos · {s['tokens']}")
    total = sum(s["cost_usd"] for s in out["steps"])
    toks = sum(sum(s["tokens"].values()) for s in out["steps"])
    print(f"total depois: {total:.4f} USD · {toks} tokens")
    if not a.quiet:
        print("--- output antes\n" + json.dumps(b.get("output"), ensure_ascii=False, indent=1)[:6000])
        for s in out["steps"]:
            print(f"--- output depois: {s['node']}\n" + json.dumps(s["output"], ensure_ascii=False, indent=1, default=str)[:6000])


if __name__ == "__main__":
    main()
