"""Executa um agente (LLM ou script) e devolve um AgentResult.

- cache de outputs (cache_ttl / cache_key no agent.yaml)
- custo, duração e turnos de cada execução (ResultMessage)
- tudo gravado em agent_outputs (data/agentock.db)
- hooks, subagentes e tools de dados (market_tools) para agentes LLM
"""
import asyncio
import hashlib
import importlib.util
import inspect
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions, ResultMessage, query
from pydantic import BaseModel

from . import db
from .hooks import build_hooks
from .spec import AgentSpec, load_agent


@dataclass
class AgentResult:
    agent: str
    status: str  # ok | failed
    output: object = None
    error: str | None = None
    cached: bool = False
    cost_usd: float | None = None
    duration_ms: int | None = None
    turns: int | None = None


class AgentError(Exception):
    def __init__(self, msg: str, meta: dict):
        super().__init__(msg)
        self.meta = meta


def to_jsonable(x):
    if isinstance(x, BaseModel):
        return x.model_dump(mode="json")
    if isinstance(x, (list, tuple)):
        return [to_jsonable(i) for i in x]
    if isinstance(x, dict):
        return {k: to_jsonable(v) for k, v in x.items()}
    return x


def dumps(x) -> str:
    return json.dumps(to_jsonable(x), ensure_ascii=False, default=str)


def new_run_id(ticker: str | None = None) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{stamp}-{(ticker or 'run').replace('.', '_')}-{uuid.uuid4().hex[:6]}"


def cache_key(spec: AgentSpec, inputs: dict) -> str:
    keys = spec.cache_key or sorted(inputs)
    payload = json.dumps({k: to_jsonable(inputs.get(k)) for k in keys}, sort_keys=True, default=str)
    return f"{spec.name}:{hashlib.sha256(payload.encode()).hexdigest()[:32]}"


def _restore(spec: AgentSpec, raw: str):
    data = json.loads(raw)
    return spec.output_model.model_validate(data) if spec.output_model else data


def persist(conn, run_id: str, node: str | None, ticker: str | None, res: AgentResult) -> None:
    db.save_agent_output(conn, run_id=run_id, node=node or res.agent, agent=res.agent, ticker=ticker,
                         status=res.status, cached=res.cached,
                         output=dumps(res.output) if res.output is not None else None, error=res.error,
                         cost_usd=res.cost_usd, duration_ms=res.duration_ms, turns=res.turns)


# ---------------------------------------------------------------- script
async def _run_script(spec: AgentSpec, inputs: dict):
    path = spec.find("run.py")
    if path is None:
        raise FileNotFoundError(f"{spec.name}: run.py não encontrado")
    mspec = importlib.util.spec_from_file_location(f"_script_{spec.name}", path)
    mod = importlib.util.module_from_spec(mspec)
    mspec.loader.exec_module(mod)
    if inspect.iscoroutinefunction(mod.run):
        return await mod.run(**inputs)
    return await asyncio.to_thread(mod.run, **inputs)  # não bloqueia os outros nós da camada


# ---------------------------------------------------------------- LLM
def _options(spec: AgentSpec, vars_: dict, ctx: dict) -> ClaudeAgentOptions:
    mcp = dict(spec.mcp_servers)
    if spec.market_tools:
        from .market_tools import build_market_server
        mcp["market"] = build_market_server(spec.market_tools)
    kwargs = dict(
        system_prompt=spec.prompt_tpl.safe_substitute(vars_),
        allowed_tools=spec.allowed_tools, mcp_servers=mcp, cwd=str(spec.asset_dir),
        setting_sources=["project"], max_turns=spec.max_turns, model=spec.model,
        hooks=build_hooks(spec.hooks, ctx),
    )
    if spec.output_model:
        kwargs["output_format"] = {"type": "json_schema", "schema": spec.output_model.model_json_schema()}
    if spec.effort:
        kwargs["effort"] = spec.effort
    if spec.max_budget_usd:
        kwargs["max_budget_usd"] = spec.max_budget_usd
    if spec.subagents:
        kwargs["agents"] = {
            n: AgentDefinition(description=d["description"], prompt=spec.read(d["prompt"]),
                               tools=d.get("tools"), model=d.get("model"))
            for n, d in spec.subagents.items()
        }
    return ClaudeAgentOptions(**kwargs)


async def _run_llm(spec: AgentSpec, inputs: dict, ctx: dict):
    vars_ = {k: (v if isinstance(v, (str, int, float)) else dumps(v)) for k, v in inputs.items()}
    vars_["now"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    result = None
    # consumir o gerador até ao fim (um return a meio deixa-o por fechar → RuntimeError no aclose)
    async for msg in query(prompt=spec.task_tpl.safe_substitute(vars_), options=_options(spec, vars_, ctx)):
        if isinstance(msg, ResultMessage):
            result = msg
    if result is None:
        raise AgentError("o agente terminou sem ResultMessage", {})
    meta = {"cost_usd": result.total_cost_usd, "duration_ms": result.duration_ms, "turns": result.num_turns}
    if result.is_error:
        raise AgentError(f"{result.subtype}: {result.errors or result.result}", meta)
    data = result.structured_output
    if data is None and spec.output_model and result.result:
        data = json.loads(result.result)
    if spec.output_model:
        return spec.output_model.model_validate(data), meta
    return (data if data is not None else result.result), meta


# ---------------------------------------------------------------- API
async def run_agent(name: str, *, run_id: str | None = None, node: str | None = None, use_cache: bool = True,
                    conn=None, agents_dir: Path | None = None, **inputs) -> AgentResult:
    conn = conn or db.connect()
    run_id = run_id or new_run_id(inputs.get("ticker"))
    t0 = time.time()
    try:
        spec = load_agent(name, agents_dir)
    except Exception as e:
        res = AgentResult(name, "failed", error=f"carregar agente: {type(e).__name__}: {e}")
        persist(conn, run_id, node, inputs.get("ticker"), res)
        return res

    missing = [i for i in spec.inputs if i not in inputs]
    key = cache_key(spec, inputs) if spec.cache_ttl else None
    if missing:
        res = AgentResult(spec.name, "failed", error=f"faltam inputs {missing}")
    elif key and use_cache and (raw := db.agent_cache_get(conn, key)):
        res = AgentResult(spec.name, "ok", _restore(spec, raw), cached=True, duration_ms=0, cost_usd=0.0)
    else:
        try:
            if spec.kind == "script":
                output, meta = await _run_script(spec, inputs), {}
            else:
                output, meta = await _run_llm(spec, inputs, {"run_id": run_id, "agent": spec.name})
            res = AgentResult(spec.name, "ok", output, **meta)
            if key:
                db.agent_cache_set(conn, key, spec.name, dumps(output), spec.cache_ttl)
        except AgentError as e:
            res = AgentResult(spec.name, "failed", error=str(e), **e.meta)
        except Exception as e:
            res = AgentResult(spec.name, "failed", error=f"{type(e).__name__}: {e}")
    if res.duration_ms is None:
        res.duration_ms = int((time.time() - t0) * 1000)
    persist(conn, run_id, node, inputs.get("ticker"), res)
    return res
