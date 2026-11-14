"""Orquestrador: corre um fluxo (flow.yaml) como DAG, camada a camada, com os nós de cada camada em paralelo.

Referências nos inputs: $param (parâmetro do trigger) · $nó (output de outro nó) · $nó.campo
As dependências deduzem-se das referências (+ `after:` explícito). Um nó que falha não pára o fluxo:
os dependentes recebem None nesse input e continuam (a síntese sabe o que falta).
"""
import asyncio
import re
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
    timeout: int = 900
    after: list[str] = field(default_factory=list)


@dataclass
class RunReport:
    run_id: str
    layers: list[list[str]]
    results: dict[str, AgentResult]

    @property
    def cost_usd(self) -> float:
        return sum(r.cost_usd or 0 for r in self.results.values())


def load_flow(flow: str | dict, path: Path | None = None) -> dict[str, Node]:
    spec = flow if isinstance(flow, dict) else \
        yaml.safe_load((path or FLOW_FILE).read_text(encoding="utf-8"))["flows"][flow]
    return {n: Node(name=n, agent=d["agent"], inputs=d.get("inputs") or {}, timeout=d.get("timeout", 900),
                    after=d.get("after") or []) for n, d in spec.items()}


def _refs(value) -> set[str]:
    if isinstance(value, str) and (m := REF.match(value)):
        return {m.group(1)}
    if isinstance(value, dict):
        return set().union(*map(_refs, value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*map(_refs, value)) if value else set()
    return set()


def deps(node: Node, nodes: dict[str, Node]) -> set[str]:
    return {r for r in _refs(node.inputs) if r in nodes} | set(node.after)


def layers(nodes: dict[str, Node]) -> list[list[str]]:
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


async def run_flow(flow: str | dict, params: dict, *, only: str | None = None, use_cache: bool = True,
                   conn=None, agents_dir: Path | None = None, run_id: str | None = None) -> RunReport:
    nodes = load_flow(flow)
    plan = [[only]] if only else layers(nodes)
    if only and only not in nodes:
        raise ValueError(f"nó desconhecido: {only}")
    conn = conn or db.connect()
    run_id = run_id or new_run_id(params.get("ticker"))
    results: dict[str, AgentResult] = {}

    async def one(name: str) -> AgentResult:
        node = nodes[name]
        inputs = resolve(node.inputs, params, results)
        try:
            return await asyncio.wait_for(
                run_agent(node.agent, run_id=run_id, node=name, use_cache=use_cache, conn=conn,
                          agents_dir=agents_dir, **inputs), node.timeout)
        except asyncio.TimeoutError:
            res = AgentResult(node.agent, "failed", error=f"timeout ({node.timeout}s)", duration_ms=node.timeout * 1000)
            persist(conn, run_id, name, params.get("ticker"), res)
            return res

    for layer in plan:
        outs = await asyncio.gather(*(one(n) for n in layer))
        results.update(zip(layer, outs))
    return RunReport(run_id, plan, results)
