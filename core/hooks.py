"""Hooks dos agentes LLM. `log_tools`, `fetch_guard` e `read_guard` estão sempre ligados; os outros ativam-se no
agent.yaml (`hooks:`).

  log_tools                      regista cada tool call (e cada recusa) em data/logs/<run_id>.jsonl
  fetch_guard                    WebFetch só a http(s) públicos e sem query strings longas (exfiltração por URL)
  read_guard                     Read/Glob/Grep só dentro da pasta do agente e das pastas da execução
  block_domains                  recusa WebFetch a domínios em config/blocked_domains.yaml
  {name: mcp_quota, server: X}   conta cada chamada a mcp__X__* no livro de quotas; recusa ao esgotar

Os agentes leem texto da web, que pode trazer instruções maliciosas (prompt injection). Estas defesas somam-se ao
isolamento da sessão (core/runner.py): só as tools declaradas existem, sem conectores MCP da conta.
"""
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import yaml
from claude_agent_sdk import HookMatcher

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "data" / "logs"
BLOCKED_FILE = ROOT / "config" / "blocked_domains.yaml"
PRIVATE_HOST = re.compile(r"^(localhost$|127\.|10\.|192\.168\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.|\[?::1\]?$|0\.0\.0\.0$)")
MAX_QUERY = 200  # caracteres de query string: chega para qualquer página de notícias; não chega para levar um ficheiro


def _log(ctx: dict, line: dict) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with (LOG_DIR / f"{ctx['run_id']}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "agent": ctx.get("agent"), **line}, ensure_ascii=False) + "\n")
    except OSError:
        pass  # o registo é acessório: nunca pode partir o agente


def _deny(reason: str, ctx: dict | None = None, inp: dict | None = None) -> dict:
    if ctx is not None:
        _log(ctx, {"event": "denied", "tool": (inp or {}).get("tool_name"), "reason": reason,
                   "input": json.dumps((inp or {}).get("tool_input"), ensure_ascii=False)[:500]})
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def log_tools(ctx: dict) -> dict:
    async def post(inp, tool_use_id, _context):
        resp = inp.get("tool_response")
        _log(ctx, {"event": inp.get("hook_event_name"), "tool": inp.get("tool_name"),
                   "input": json.dumps(inp.get("tool_input"), ensure_ascii=False)[:500],
                   "response_chars": len(json.dumps(resp, ensure_ascii=False, default=str)) if resp else 0,
                   "error": inp.get("error")})
        return {}

    return {"PostToolUse": [HookMatcher(matcher=None, hooks=[post])],
            "PostToolUseFailure": [HookMatcher(matcher=None, hooks=[post])]}


def fetch_problem(url: str) -> str | None:
    """Motivo para recusar um WebFetch, ou None se o endereço for aceitável."""
    u = urlparse(url or "")
    if u.scheme not in ("http", "https") or not u.hostname:
        return "só são aceites endereços http(s)"
    if PRIVATE_HOST.match(u.hostname.lower()) or u.hostname.lower().endswith((".local", ".internal")):
        return f"endereço interno: {u.hostname}"
    if len(u.query) > MAX_QUERY or len(url) > 600:
        return "endereço com parâmetros demasiado longos"
    return None


def fetch_guard(ctx: dict) -> dict:
    async def pre(inp, tool_use_id, _context):
        why = fetch_problem((inp.get("tool_input") or {}).get("url", ""))
        return _deny(why, ctx, inp) if why else {}

    return {"PreToolUse": [HookMatcher(matcher="WebFetch", hooks=[pre])]}


def inside(path: str, dirs: list[str]) -> bool:
    try:
        target = Path(path).resolve()
    except (OSError, ValueError):
        return False
    for d in dirs:
        try:
            target.relative_to(Path(d).resolve())
            return True
        except ValueError:
            continue
    return False


def read_guard(ctx: dict) -> dict:
    """Um agente só lê ficheiros da sua pasta e das pastas desta execução — nunca .env, credenciais ou o resto do disco."""
    dirs = [str(d) for d in ctx.get("dirs") or []]

    async def pre(inp, tool_use_id, _context):
        ti = inp.get("tool_input") or {}
        path = ti.get("file_path") or ti.get("path") or (dirs[0] if dirs else "")
        if not dirs or not inside(path, dirs) or ".." in str(ti.get("pattern") or ""):
            return _deny("leitura fora da pasta do agente", ctx, inp)
        return {}

    return {"PreToolUse": [HookMatcher(matcher="Read|Glob|Grep", hooks=[pre])]}


def block_domains(ctx: dict) -> dict:
    blocked = set((yaml.safe_load(BLOCKED_FILE.read_text(encoding="utf-8")) or {}).get("domains", [])) \
        if BLOCKED_FILE.exists() else set()

    async def pre(inp, tool_use_id, _context):
        host = urlparse((inp.get("tool_input") or {}).get("url", "")).hostname or ""
        if any(host == d or host.endswith("." + d) for d in blocked):
            return _deny(f"domínio bloqueado: {host}", ctx, inp)
        return {}

    return {"PreToolUse": [HookMatcher(matcher="WebFetch", hooks=[pre])]}


def mcp_quota(ctx: dict, server: str) -> dict:
    from .data import get_router
    router = get_router()

    async def pre(inp, tool_use_id, _context):
        if not router.store.allow(server, router.limits(server)):
            return _deny(f"quota esgotada para {server}", ctx, inp)
        router.store.record(server)
        return {}

    return {"PreToolUse": [HookMatcher(matcher=f"mcp__{server}__.*", hooks=[pre])]}


REGISTRY = {"log_tools": log_tools, "fetch_guard": fetch_guard, "read_guard": read_guard,
            "block_domains": block_domains, "mcp_quota": mcp_quota}
ALWAYS = ("log_tools", "fetch_guard", "read_guard")


def build_hooks(entries: list, ctx: dict) -> dict:
    """Junta os hooks pedidos (mais os que estão sempre ligados) num dict {evento: [HookMatcher]}."""
    merged: dict[str, list] = {}
    seen = set()
    for entry in [*ALWAYS, *entries]:
        name, params = (entry, {}) if isinstance(entry, str) else (entry["name"], {k: v for k, v in entry.items() if k != "name"})
        key = (name, json.dumps(params, sort_keys=True))
        if key in seen:
            continue
        seen.add(key)
        for event, matchers in REGISTRY[name](ctx, **params).items():
            merged.setdefault(event, []).extend(matchers)
    return merged
