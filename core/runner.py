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
import os
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
    status: str  # ok | failed | skipped
    output: object = None
    error: str | None = None
    cached: bool = False
    cost_usd: float | None = None
    duration_ms: int | None = None
    turns: int | None = None
    usage: dict | None = None  # tokens por modelo: {modelo: {input, cache_write, cache_read, output, cost}}


_SLOTS: dict = {}


def llm_slots() -> asyncio.Semaphore:
    """Limita agentes LLM em simultâneo (AGENTOCK_LLM_PARALLEL, por omissão 4). Um semáforo por event loop."""
    loop = asyncio.get_running_loop()
    if loop not in _SLOTS:
        _SLOTS.clear()
        _SLOTS[loop] = asyncio.Semaphore(int(os.environ.get("AGENTOCK_LLM_PARALLEL", "4")))
    return _SLOTS[loop]


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


def _path(inputs: dict, key: str):
    head, _, rest = key.partition(".")
    v = to_jsonable(inputs.get(head))
    for part in filter(None, rest.split(".")):
        v = v.get(part) if isinstance(v, dict) else None
    return v


def cache_key(spec: AgentSpec, inputs: dict) -> str:
    """cache_key aceita caminhos (ex.: profile.symbol) para não depender de campos voláteis como o preço."""
    keys = spec.cache_key or sorted(inputs)
    payload = json.dumps({k: _path(inputs, k) for k in keys}, sort_keys=True, default=str)
    return f"{spec.name}:{hashlib.sha256(payload.encode()).hexdigest()[:32]}"


def _restore(spec: AgentSpec, raw: str):
    data = json.loads(raw)
    return spec.output_model.model_validate(data) if spec.output_model else data


def normalize_usage(model_usage: dict | None) -> dict | None:
    """`ResultMessage.model_usage` do SDK (camelCase, por modelo, inclui subagentes) → formato gravado."""
    if not model_usage:
        return None
    return {m: {"input": u.get("inputTokens", 0), "cache_write": u.get("cacheCreationInputTokens", 0),
                "cache_read": u.get("cacheReadInputTokens", 0), "output": u.get("outputTokens", 0),
                "cost": u.get("costUSD", 0.0)} for m, u in model_usage.items()}


def persist(conn, run_id: str, node: str | None, ticker: str | None, res: AgentResult) -> None:
    db.save_agent_output(conn, run_id=run_id, node=node or res.agent, agent=res.agent, ticker=ticker,
                         status=res.status, cached=res.cached,
                         output=dumps(res.output) if res.output is not None else None, error=res.error,
                         cost_usd=res.cost_usd, duration_ms=res.duration_ms, turns=res.turns,
                         usage=json.dumps(res.usage) if res.usage else None)


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
RUNS_DIR = Path(__file__).resolve().parent.parent / "data" / "runs"


def _write_file_inputs(spec: AgentSpec, inputs: dict, vars_: dict, run_id: str) -> list[str]:
    if not spec.file_inputs:
        return []
    d = RUNS_DIR / run_id / spec.name
    d.mkdir(parents=True, exist_ok=True)
    for name in spec.file_inputs:
        p = d / f"{name}.json"
        p.write_text(json.dumps(to_jsonable(inputs.get(name)), ensure_ascii=False, indent=1, default=str),
                     encoding="utf-8")
        vars_[f"{name}_file"] = p.as_posix()
    return [str(d)]


def _options(spec: AgentSpec, vars_: dict, ctx: dict, add_dirs: list[str] | None = None) -> ClaudeAgentOptions:
    mcp = dict(spec.mcp_servers)
    if spec.market_tools:
        from .market_tools import build_market_server
        mcp["market"] = build_market_server(spec.market_tools)
    # Sessão isolada (D24): no contexto só entra o que é do agente. Sem isto cada sessão herdava as 16 tools do
    # Claude Code, a lista de skills globais e os conectores MCP da conta (~45 mil tokens por agente, e conectores
    # pessoais visíveis a agentes que leem a web).
    kwargs = dict(
        system_prompt=spec.system_prompt(vars_),
        tools=spec.builtin_tools, allowed_tools=spec.allowed_tools, skills=[],
        mcp_servers=mcp, strict_mcp_config=True, cwd=str(spec.asset_dir),
        setting_sources=[], env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"},
        max_turns=spec.max_turns, model=spec.model, hooks=build_hooks(spec.hooks, ctx),
    )
    if spec.output_model:
        kwargs["output_format"] = {"type": "json_schema", "schema": spec.output_model.model_json_schema()}
    if spec.effort:
        kwargs["effort"] = spec.effort
    if spec.max_budget_usd:
        kwargs["max_budget_usd"] = spec.max_budget_usd
    if add_dirs:
        kwargs["add_dirs"] = add_dirs
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
    add_dirs = _write_file_inputs(spec, inputs, vars_, ctx["run_id"])
    result = None
    # consumir o gerador até ao fim (um return a meio deixa-o por fechar → RuntimeError no aclose)
    async for msg in query(prompt=spec.task_tpl.safe_substitute(vars_), options=_options(spec, vars_, ctx, add_dirs)):
        if isinstance(msg, ResultMessage):
            result = msg
    if result is None:
        raise AgentError("o agente terminou sem ResultMessage", {})
    meta = {"cost_usd": result.total_cost_usd, "duration_ms": result.duration_ms, "turns": result.num_turns,
            "usage": normalize_usage(result.model_usage)}
    if result.is_error:
        raise AgentError(f"{result.subtype}: {result.errors or result.result}", meta)
    data = result.structured_output
    if data is None and spec.output_model and result.result:
        data = json.loads(result.result)
    if spec.output_model:
        return spec.output_model.model_validate(data), meta
    return (data if data is not None else result.result), meta


# ---------------------------------------------------------------- API
async def run_agent(name: str, inputs: dict | None = None, *, run_id: str | None = None, node: str | None = None,
                    use_cache: bool = True, conn=None, agents_dir: Path | None = None, **kw_inputs) -> AgentResult:
    """inputs: dict (preferível — nenhum nome de input colide com estes argumentos) ou **kw_inputs."""
    inputs = {**(inputs or {}), **kw_inputs}
    conn = conn or db.connect()
    run_id = run_id or new_run_id(inputs.get("ticker"))
    t0 = time.time()
    try:
        spec = load_agent(name, agents_dir)
    except Exception as e:
        res = AgentResult(name, "failed", error=f"carregar agente: {type(e).__name__}: {e}")
        persist(conn, run_id, node, inputs.get("ticker"), res)
        return res

    inputs = {**spec.defaults, **{k: v for k, v in inputs.items() if v is not None or k not in spec.defaults}}
    missing = [i for i in spec.inputs if i not in inputs]
    empty = [i for i in spec.inputs if i in inputs and inputs[i] is None]
    key = cache_key(spec, inputs) if spec.cache_ttl else None
    if missing:
        res = AgentResult(spec.name, "failed", error=f"faltam inputs {missing}")
    elif empty:
        res = AgentResult(spec.name, "skipped", error=f"sem dados de entrada {empty} (nó a montante falhou)")
    elif key and use_cache and (raw := db.agent_cache_get(conn, key)):
        res = AgentResult(spec.name, "ok", _restore(spec, raw), cached=True, duration_ms=0, cost_usd=0.0)
    else:
        try:
            if spec.kind == "script":
                output, meta = await _run_script(spec, inputs), {}
            else:
                async with llm_slots():
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
