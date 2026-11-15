"""Medição do Agentock a partir de dados já gravados (não corre agentes, não gasta nada).

  python tools/measure.py                 # resumo das execuções completas (custo, tempo, tokens, caminho crítico)
  python tools/measure.py --run RUN_ID    # uma execução ao pormenor
  python tools/measure.py --json          # tudo em JSON (para comparar antes/depois)

Fontes:
  data/agentock.db (agent_outputs)        custo, duração, turnos e — desde a Fase 10 — tokens por nó
  ~/.claude/projects/*Agentock-agents-*   transcrições das sessões dos agentes (tokens por modelo, pedidos à API,
                                          composição do 1.º pedido); servem para as execuções anteriores à Fase 10
"""
import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.orchestrator import deps, layers, load_flow  # noqa: E402

DB = ROOT / "data" / "agentock.db"
TRANSCRIPTS = Path.home() / ".claude" / "projects"
TOK = ("input", "cache_write", "cache_read", "output")


def _ts(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()


# ------------------------------------------------------------------ transcrições
def _session(path: Path) -> dict | None:
    """Resumo de uma sessão: tokens por modelo (cost-state), pedidos à API e composição do 1.º pedido."""
    first = last = None
    cost = None
    usage: dict = {}
    requests, tool_chars, tools = 0, 0, defaultdict(int)
    shape = {}
    seen_msgs = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ts := o.get("timestamp"):
            t = _ts(ts)
            first, last = (t if first is None else min(first, t)), (t if last is None else max(last, t))
        typ = o.get("type")
        if typ == "cost-state":
            cost, usage = o.get("totalCostUSD"), o.get("modelUsage") or {}
        elif typ == "api-request":
            requests += 1
        elif typ == "api-request-shape" and not shape:
            sh = o.get("shape") or {}
            shape = {"system_chars": sum(len(x.get("text", "")) for x in sh.get("system", [])),
                     "tools_chars": len(json.dumps(sh.get("tools", []))), "n_tools": len(sh.get("tools", [])),
                     "tool_names": [t.get("name") for t in sh.get("tools", [])]}
        elif typ == "attachment":
            a = o.get("attachment") or {}
            if a.get("type") in ("skill_listing", "agent_listing_delta", "instructions", "session_context"):
                shape.setdefault("attach_" + a["type"], len(json.dumps(a, ensure_ascii=False)))
        elif typ == "user":
            c = (o.get("message") or {}).get("content")
            if isinstance(c, str):
                shape.setdefault("task_chars", len(c))
            else:
                for part in c or []:
                    if part.get("type") == "tool_result":
                        tool_chars += len(json.dumps(part.get("content"), ensure_ascii=False))
                    elif part.get("type") == "text":
                        shape.setdefault("task_chars", len(part.get("text", "")))
        elif typ == "assistant":
            m = o.get("message") or {}
            for part in m.get("content") or []:
                if part.get("type") == "tool_use" and (m.get("id"), part.get("id")) not in seen_msgs:
                    seen_msgs.add((m.get("id"), part.get("id")))
                    tools[part.get("name")] += 1
    if first is None or cost is None:
        return None
    tokens = {m: {"input": u.get("inputTokens", 0), "cache_write": u.get("cacheCreationInputTokens", 0),
                  "cache_read": u.get("cacheReadInputTokens", 0), "output": u.get("outputTokens", 0),
                  "cost": u.get("costUSD", 0.0)} for m, u in usage.items()}
    return {"file": str(path), "slug": path.parent.name, "start": first, "end": last, "cost": cost, "tokens": tokens,
            "requests": requests, "tool_result_chars": tool_chars, "tools": dict(tools), "shape": shape}


def load_sessions() -> list[dict]:
    out = []
    for d in TRANSCRIPTS.glob("*Agentock-agents-*"):
        for f in d.glob("*.jsonl"):
            if s := _session(f):
                out.append(s)
    return out


def total_tokens(tokens: dict) -> dict:
    return {k: sum(m[k] for m in tokens.values()) for k in TOK}


# ------------------------------------------------------------------ base de dados
def load_runs(conn) -> dict[str, list[dict]]:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(agent_outputs)")}
    extra = ", usage" if "usage" in cols else ""
    runs = defaultdict(list)
    for r in conn.execute(f"SELECT run_id, node, agent, ts, status, cached, cost_usd, duration_ms, turns, error,"
                          f" length(output) AS out_chars{extra} FROM agent_outputs ORDER BY id"):
        d = dict(r)
        d["end"] = _ts(d["ts"])
        d["start"] = d["end"] - (d["duration_ms"] or 0) / 1000
        d["tokens"] = None
        if d.get("usage"):
            try:
                d["tokens"] = json.loads(d["usage"])
            except json.JSONDecodeError:
                pass
        runs[d["run_id"]].append(d)
    return runs


def attach_sessions(runs: dict, sessions: list[dict]) -> None:
    """Liga cada nó LLM à sua sessão pelo custo (igual até ao 6.º decimal) e pela hora de fim."""
    for rows in runs.values():
        for r in rows:
            if r["tokens"] or not r["cost_usd"]:
                continue
            best = [s for s in sessions if abs(s["cost"] - r["cost_usd"]) < 1e-6 and abs(s["end"] - r["end"]) < 30]
            if best:
                s = min(best, key=lambda s: abs(s["end"] - r["end"]))
                r["tokens"], r["session"] = s["tokens"], s


def critical_path(rows: list[dict], nodes: dict) -> dict:
    """Tempo real vs. tempo se cada nó arrancasse assim que as suas dependências terminam (sem camadas)."""
    dur = {r["node"]: (r["duration_ms"] or 0) / 1000 for r in rows}
    present = {n: nd for n, nd in nodes.items() if n in dur}
    finish, via = {}, {}
    for layer in layers(present):
        for n in layer:
            ds = [d for d in deps(present[n], present)]
            start = max((finish[d] for d in ds), default=0.0)
            via[n] = max(ds, key=lambda d: finish[d]) if ds else None
            finish[n] = start + dur[n]
    end = max(finish, key=finish.get)
    path, n = [], end
    while n:
        path.append(n)
        n = via[n]
    layered = sum(max(dur[n] for n in layer) for layer in layers(present))
    return {"ideal_s": round(finish[end], 1), "layered_s": round(layered, 1),
            "path": [(n, round(dur[n], 1)) for n in reversed(path) if dur[n] >= 0.5]}


def summarize(run_id: str, rows: list[dict], nodes: dict) -> dict:
    tok = {k: 0 for k in TOK}
    by_model = defaultdict(lambda: {k: 0 for k in TOK} | {"cost": 0.0})
    covered = 0
    for r in rows:
        if r["tokens"]:
            covered += 1
            for m, u in r["tokens"].items():
                for k in TOK:
                    tok[k] += u.get(k, 0)
                    by_model[m][k] += u.get(k, 0)
                by_model[m]["cost"] += u.get("cost", 0.0)
    llm = [r for r in rows if r["cost_usd"]]
    return {
        "run_id": run_id, "ticker": rows[0].get("ticker") if rows else None,
        "nodes": len(rows), "ok": sum(r["status"] == "ok" for r in rows),
        "failed": [r["node"] for r in rows if r["status"] == "failed"],
        "skipped": [r["node"] for r in rows if r["status"] == "skipped"],
        "cached": sum(bool(r["cached"]) for r in rows),
        "llm_nodes": len(llm), "llm_with_tokens": covered,
        "cost_usd": round(sum(r["cost_usd"] or 0 for r in rows), 4),
        "turns": sum(r["turns"] or 0 for r in rows),
        "wall_s": round(max(r["end"] for r in rows) - min(r["start"] for r in rows), 1),
        "sum_s": round(sum((r["duration_ms"] or 0) for r in rows) / 1000, 1),
        "tokens": tok, "tokens_total": sum(tok.values()),
        "by_model": {m: {**{k: v[k] for k in TOK}, "cost": round(v["cost"], 4)} for m, v in by_model.items()},
        "critical": critical_path(rows, nodes),
    }


def collect(flow: str = "ticker") -> dict:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    runs = load_runs(conn)
    sessions = load_sessions()
    attach_sessions(runs, sessions)
    nodes = load_flow(flow)
    full = {rid: rows for rid, rows in runs.items() if len({r["node"] for r in rows} & set(nodes)) >= 25}
    return {"runs": runs, "full": full, "nodes": nodes, "sessions": sessions,
            "summaries": {rid: summarize(rid, rows, nodes) for rid, rows in full.items()}}


def node_table(full: dict) -> list[dict]:
    """Média por nó nas execuções completas, só execuções reais (sem cache)."""
    acc = defaultdict(list)
    for rows in full.values():
        for r in rows:
            if not r["cached"] and r["status"] == "ok":
                acc[r["node"]].append(r)
    out = []
    for node, rs in acc.items():
        n = len(rs)
        toks = [total_tokens(r["tokens"]) for r in rs if r["tokens"]]
        avg = lambda xs: sum(xs) / len(xs) if xs else 0  # noqa: E731
        out.append({"node": node, "n": n, "cost": avg([r["cost_usd"] or 0 for r in rs]),
                    "dur": avg([(r["duration_ms"] or 0) / 1000 for r in rs]), "max_dur": max((r["duration_ms"] or 0) / 1000 for r in rs),
                    "turns": avg([r["turns"] or 0 for r in rs]),
                    **{k: avg([t[k] for t in toks]) for k in TOK},
                    "requests": avg([r["session"]["requests"] for r in rs if r.get("session")]),
                    "tool_chars": avg([r["session"]["tool_result_chars"] for r in rs if r.get("session")])})
    return sorted(out, key=lambda d: -d["cost"])


def fmt_k(x: float) -> str:
    return f"{x / 1000:.1f}k" if x else "—"


def print_summary(data: dict) -> None:
    print("| Execução | Nós ok | Falhas/skips | Cache | Custo USD | Turnos | Tempo real | Ideal (DAG) | Tokens in novos | "
          "Cache write | Cache read | Out |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for rid, s in data["summaries"].items():
        t = s["tokens"]
        print(f"| {rid} | {s['ok']}/{s['nodes']} | {len(s['failed'])}/{len(s['skipped'])} | {s['cached']} | "
              f"{s['cost_usd']:.2f} | {s['turns']} | {s['wall_s']:.0f} s | {s['critical']['ideal_s']:.0f} s | "
              f"{fmt_k(t['input'])} | {fmt_k(t['cache_write'])} | {fmt_k(t['cache_read'])} | {fmt_k(t['output'])} |")
    print("\n| Nó | n | Custo | Duração média (máx.) | Turnos | Pedidos API | In novo | Cache write | Cache read | Out | Tools (chars) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for d in node_table(data["full"]):
        if d["cost"] or d["dur"] >= 1:
            print(f"| {d['node']} | {d['n']} | {d['cost']:.3f} | {d['dur']:.1f} s ({d['max_dur']:.0f}) | {d['turns']:.1f} | "
                  f"{d['requests']:.1f} | {fmt_k(d['input'])} | {fmt_k(d['cache_write'])} | {fmt_k(d['cache_read'])} | "
                  f"{fmt_k(d['output'])} | {fmt_k(d['tool_chars'])} |")
    for rid, s in data["summaries"].items():
        print(f"\n{rid}: caminho crítico {' → '.join(f'{n} {d:.0f}s' for n, d in s['critical']['path'])}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--run")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    data = collect()
    if a.json:
        print(json.dumps({"summaries": data["summaries"], "nodes": node_table(data["full"])}, ensure_ascii=False,
                         indent=1, default=str))
    elif a.run:
        rows = data["runs"][a.run]
        print(json.dumps(summarize(a.run, rows, data["nodes"]), ensure_ascii=False, indent=1))
        for r in rows:
            t = total_tokens(r["tokens"]) if r["tokens"] else {}
            print(f"  {r['node']:17} {r['status']:7} {'cache' if r['cached'] else '':5} ${r['cost_usd'] or 0:.3f} "
                  f"{(r['duration_ms'] or 0) / 1000:6.1f}s turnos={r['turns'] or 0:2} {t}")
    else:
        print_summary(data)


if __name__ == "__main__":
    main()
