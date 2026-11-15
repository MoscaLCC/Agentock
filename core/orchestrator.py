"""Orquestrador: corre um fluxo (flow.yaml) como DAG. Cada nó arranca assim que as SUAS dependências terminam
(antes da Fase 10 corria camada a camada: um nó lento atrasava todos os da camada seguinte — 211 s vs 148 s).

Referências nos inputs: $param (parâmetro do trigger) · $nó (output de outro nó) · $nó.campo
As dependências deduzem-se das referências (+ `after:` explícito). Um nó que falha não pára o fluxo:
os dependentes recebem None nesse input e continuam (a síntese sabe o que falta).

`when: $param` desliga o nó quando o parâmetro é falso (estado `off`: não é falha nem lacuna).
`on_event` recebe {"type": "start"|"done", "node", "status", "cached", "done", "total", ...} — progresso no bot.
`cancel` (asyncio.Event) interrompe os nós a correr e marca os restantes como `cancelled`.
`resume=True` com um `run_id` já gravado reaproveita os nós `ok` dessa execução (retoma depois de um crash).
"""
import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel

from . import db
from .runner import AgentResult, new_run_id, persist, run_agent

FLOW_FILE = Path(__file__).resolve().parent.parent / "flow.yaml"
REF = re.compile(r"^\$([A-Za-z_]\w*)((?:\.\w+)*)$")


@dataclass
class Node:
    name: str
    agent: str
    inputs: dict = field(default_factory=dict)
    timeout: float = 300
    after: list[str] = field(default_factory=list)
    when: object = True


@dataclass
class RunReport:
    run_id: str
    layers: list[list[str]]
    results: dict[str, AgentResult]
    duration_s: float = 0.0
    cancelled: bool = False

    @property
    def cost_usd(self) -> float:
        return sum(r.cost_usd or 0 for r in self.results.values())

    def problems(self) -> dict[str, AgentResult]:
        """Nós que não deram resultado (falhados, saltados por falta de input, cancelados). `off` não conta."""
        return {n: r for n, r in self.results.items() if r.status not in ("ok", "off")}

    def tokens(self) -> dict[str, int]:
        out = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
        for r in self.results.values():
            for u in (r.usage or {}).values():
                for k in out:
                    out[k] += u.get(k, 0)
        return out


def _flow_spec(flow: str | dict, path: Path | None = None) -> dict:
    spec = flow if isinstance(flow, dict) else \
        yaml.safe_load((path or FLOW_FILE).read_text(encoding="utf-8"))["flows"][flow]
    return spec if "nodes" in spec else {"defaults": {}, "nodes": spec}


def flow_defaults(flow: str | dict, path: Path | None = None) -> dict:
    return dict(_flow_spec(flow, path).get("defaults") or {})


def load_flow(flow: str | dict, path: Path | None = None) -> dict[str, Node]:
    """Aceita {nó: {...}} ou {defaults: {...}, nodes: {nó: {...}}}."""
    nodes = _flow_spec(flow, path)["nodes"]
    return {n: Node(name=n, agent=d["agent"], inputs=d.get("inputs") or {}, timeout=d.get("timeout", 300),
                    after=d.get("after") or [], when=d.get("when", True)) for n, d in nodes.items()}


def _refs(value) -> set[str]:
    if isinstance(value, str) and (m := REF.match(value)):
        return {m.group(1)}
    if isinstance(value, dict):
        return set().union(*map(_refs, value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*map(_refs, value)) if value else set()
    return set()


def deps(node: Node, nodes: dict[str, Node]) -> set[str]:
    return {r for r in _refs(node.inputs) | _refs(node.when) if r in nodes} | set(node.after)


def layers(nodes: dict[str, Node]) -> list[list[str]]:
    """Ordem topológica por níveis (para o `--dry-run` e para criar as tarefas pela ordem certa)."""
    pending = {n: deps(node, nodes) for n, node in nodes.items()}
    for n, ds in pending.items():
        if unknown := ds - set(nodes):
            raise ValueError(f"{n}: depende de nós inexistentes {sorted(unknown)}")
    out, done = [], set()
    while pending:
        ready = sorted(n for n, ds in pending.items() if ds <= done)
        if not ready:
            raise ValueError(f"ciclo no fluxo: {sorted(pending)}")
        out.append(ready)
        done |= set(ready)
        for n in ready:
            del pending[n]
    return out


def _walk(base, path: str):
    for part in filter(None, path.split(".")):
        if base is None:
            return None
        base = getattr(base, part, None) if isinstance(base, BaseModel) else (base or {}).get(part)
    return base


def resolve(value, params: dict, results: dict[str, AgentResult]):
    if isinstance(value, str) and (m := REF.match(value)):
        head, path = m.group(1), m.group(2)
        if head in results:
            r = results[head]
            return _walk(r.output if r.status == "ok" else None, path)
        if head in params:
            return _walk(params[head], path)
        return value
    if isinstance(value, dict):
        return {k: resolve(v, params, results) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, params, results) for v in value]
    return value


def recorded_results(conn, run_id: str) -> dict[str, AgentResult]:
    """Nós `ok` já gravados de uma execução (para a retomar sem os repetir nem voltar a pagar)."""
    out = {}
    for r in conn.execute("SELECT node, agent, output, cost_usd, turns FROM agent_outputs"
                          " WHERE run_id=? AND status='ok' AND output IS NOT NULL ORDER BY id", (run_id,)):
        out[r["node"]] = AgentResult(r["agent"], "ok", json.loads(r["output"]), cached=True, cost_usd=0.0, duration_ms=0)
    return out


async def run_flow(flow: str | dict, params: dict, *, only: str | None = None, use_cache: bool = True,
                   conn=None, agents_dir: Path | None = None, run_id: str | None = None,
                   on_event=None, cancel: asyncio.Event | None = None, resume: bool = False) -> RunReport:
    nodes = load_flow(flow)
    params = {**flow_defaults(flow), **{k: v for k, v in params.items() if v is not None}}
    if only and only not in nodes:
        raise ValueError(f"nó desconhecido: {only}")
    plan = [[only]] if only else layers(nodes)
    order = [n for layer in plan for n in layer]
    conn = conn or db.connect()
    run_id = run_id or new_run_id(params.get("ticker"))
    params["run_id"] = run_id  # disponível nos fluxos como $run_id
    ticker = params.get("ticker")
    previous = recorded_results(conn, run_id) if resume else {}
    results: dict[str, AgentResult] = {}
    tasks: dict[str, asyncio.Task] = {}
    reused: set[str] = set()
    t0 = time.time()

    def emit(kind: str, name: str, **extra) -> None:
        if on_event is None:
            return
        try:  # o progresso é acessório: um erro a mostrá-lo nunca pode partir a análise
            on_event({"type": kind, "node": name, "run_id": run_id, "done": len(results), "total": len(order),
                      "elapsed_s": round(time.time() - t0, 1), **extra})
        except Exception:  # noqa: BLE001
            pass

    def finish(name: str, res: AgentResult, save: bool = False) -> AgentResult:
        if save:
            persist(conn, run_id, name, ticker, res)
        results[name] = res
        emit("done", name, status=res.status, cached=res.cached, error=res.error,
             duration_s=round((res.duration_ms or 0) / 1000, 1))
        return res

    async def one(name: str) -> AgentResult:
        node = nodes[name]
        try:
            ds = [tasks[d] for d in deps(node, nodes) if d in tasks]
            if ds:
                await asyncio.wait(ds)
            if cancel is not None and cancel.is_set():
                raise asyncio.CancelledError
            # retoma: só se reaproveita um nó cujas dependências também foram todas reaproveitadas — se um nó a
            # montante falhou da 1.ª vez e corre agora, o que dependia dele (ex.: o dossier) tem de ser refeito
            if name in previous and all(d in reused for d in deps(node, nodes)):
                reused.add(name)
                return finish(name, previous[name])
            agent = resolve(node.agent, params, results)  # permite `agent: $rating_agent`
            if not resolve(node.when, params, results):
                return finish(name, AgentResult(str(agent), "off", error="desligado nesta execução", duration_ms=0),
                              save=True)
            inputs = resolve(node.inputs, params, results)
            emit("start", name)
            res = await run_agent(agent, inputs, run_id=run_id, node=name, use_cache=use_cache, conn=conn,
                                  agents_dir=agents_dir, timeout=node.timeout)
            return finish(name, res)
        except asyncio.CancelledError:
            return finish(name, AgentResult(str(node.agent), "cancelled", error="cancelado pelo utilizador"), save=True)

    for name in order:  # ordem topológica: as tarefas das dependências já existem
        tasks[name] = asyncio.create_task(one(name), name=f"{run_id}:{name}")

    async def watch_cancel() -> None:
        await cancel.wait()
        for t in tasks.values():
            t.cancel()

    watcher = asyncio.create_task(watch_cancel()) if cancel is not None else None
    try:
        await asyncio.gather(*tasks.values())
    except asyncio.CancelledError:  # o próprio run_flow foi cancelado: não deixar nós órfãos
        for t in tasks.values():
            t.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
        raise
    finally:
        if watcher is not None:
            watcher.cancel()
    return RunReport(run_id, plan, {n: results[n] for n in order if n in results},
                     duration_s=round(time.time() - t0, 2), cancelled=bool(cancel is not None and cancel.is_set()))
