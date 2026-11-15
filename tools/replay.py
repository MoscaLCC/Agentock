"""Reexecuta UM nó de uma análise gravada, com os mesmos inputs, para comparar antes/depois (A/B).

  python tools/replay.py RUN_ID NÓ                    # ex.: 20261114T225146-coupang-d7df77 timing
  python tools/replay.py RUN_ID NÓ --model claude-sonnet-5-5   # mesmo input, outro modelo
  python tools/replay.py RUN_ID NÓ --agent rating_v1_agent     # mesmo input, outro agente

Os inputs são reconstruídos a partir dos outputs gravados dos nós a montante (tabela agent_outputs).
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
from core import db, spec as spec_mod  # noqa: E402
from core.orchestrator import flow_defaults, load_flow, resolve  # noqa: E402
from core.runner import AgentResult, run_agent, to_jsonable  # noqa: E402

REPLAY_DB = ROOT / "data" / "replay.db"


def recorded(conn, run_id: str) -> dict[str, dict]:
    rows = conn.execute("SELECT * FROM agent_outputs WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
    return {r["node"]: dict(r) for r in rows}


def node_inputs(conn, run_id: str, node: str, flow: str = "ticker", params: dict | None = None) -> tuple[str, dict]:
    """(agente, inputs) do nó tal como o orquestrador os resolveria nessa execução."""
    nodes, rec = load_flow(flow), recorded(conn, run_id)
    if node not in nodes:
        raise ValueError(f"nó desconhecido: {node}")
    results = {n: AgentResult(r["agent"], r["status"], json.loads(r["output"]) if r["output"] else None)
               for n, r in rec.items()}
    prof = (results.get("profile").output or {}) if results.get("profile") else {}
    params = {**flow_defaults(flow), "ticker": prof.get("symbol"), "run_id": run_id, **(params or {})}
    return resolve(nodes[node].agent, params, results), resolve(nodes[node].inputs, params, results)


def tokens(usage: dict | None) -> dict:
    keys = ("input", "cache_write", "cache_read", "output")
    return {k: sum(u.get(k, 0) for u in (usage or {}).values()) for k in keys}


async def replay(run_id: str, node: str, *, agent: str | None = None, model: str | None = None,
                 flow: str = "ticker") -> dict:
    src = db.connect()
    rec = recorded(src, run_id).get(node)
    name, inputs = node_inputs(src, run_id, node, flow)
    name = agent or name
    if model:  # A/B de modelo: sobrepõe só nesta chamada
        original = spec_mod.load_agent

        def patched(n, agents_dir=None):
            s = original(n, agents_dir)
            if n == name:
                s.model = model
            return s
        import core.runner as runner
        runner.load_agent = patched
    res = await run_agent(name, inputs, run_id=f"replay-{run_id[-6:]}-{node}", node=node, use_cache=False,
                          conn=db.connect(REPLAY_DB))
    return {"node": node, "agent": name, "model": model, "status": res.status, "error": res.error,
            "before": None if not rec else {"cost_usd": rec["cost_usd"], "duration_s": (rec["duration_ms"] or 0) / 1000,
                                            "turns": rec["turns"], "output": json.loads(rec["output"] or "null")},
            "after": {"cost_usd": res.cost_usd, "duration_s": (res.duration_ms or 0) / 1000, "turns": res.turns,
                      "tokens": tokens(res.usage), "usage": res.usage, "output": to_jsonable(res.output)}}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("run_id")
    p.add_argument("node")
    p.add_argument("--agent")
    p.add_argument("--model")
    p.add_argument("--flow", default="ticker")
    p.add_argument("--quiet", action="store_true", help="não imprime os outputs completos")
    a = p.parse_args()
    out = asyncio.run(replay(a.run_id, a.node, agent=a.agent, model=a.model, flow=a.flow))
    b, af = out["before"] or {}, out["after"]
    print(f"{out['node']} ({out['agent']}{', ' + a.model if a.model else ''}): {out['status']} {out['error'] or ''}")
    print(f"  antes : {b.get('cost_usd') or 0:.4f} USD · {b.get('duration_s') or 0:.1f} s · {b.get('turns')} turnos")
    print(f"  depois: {af['cost_usd'] or 0:.4f} USD · {af['duration_s']:.1f} s · {af['turns']} turnos · tokens {af['tokens']}")
    if not a.quiet:
        print("--- output antes\n" + json.dumps(b.get("output"), ensure_ascii=False, indent=1)[:6000])
        print("--- output depois\n" + json.dumps(af["output"], ensure_ascii=False, indent=1, default=str)[:6000])


if __name__ == "__main__":
    main()
