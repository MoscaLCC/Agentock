"""Hooks dos agentes LLM. Ativados no agent.yaml (`hooks:`); `log_tools` está sempre ligado.

  log_tools                      regista cada tool call em data/logs/<run_id>.jsonl
  block_domains                  recusa WebFetch a domínios em config/blocked_domains.yaml
  {name: mcp_quota, server: X}   conta cada chamada a mcp__X__* no livro de quotas; recusa ao esgotar
"""
import json
import time
from pathlib import Path
from urllib.parse import urlparse

import yaml
from claude_agent_sdk import HookMatcher

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "data" / "logs"
BLOCKED_FILE = ROOT / "config" / "blocked_domains.yaml"


def _deny(reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def log_tools(ctx: dict) -> dict:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"{ctx['run_id']}.jsonl"

    async def post(inp, tool_use_id, _context):
        resp = inp.get("tool_response")
        line = {"ts": time.time(), "agent": ctx["agent"], "event": inp.get("hook_event_name"),
                "tool": inp.get("tool_name"), "input": json.dumps(inp.get("tool_input"), ensure_ascii=False)[:500],
                "response_chars": len(json.dumps(resp, ensure_ascii=False, default=str)) if resp else 0,
                "error": inp.get("error")}
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
        return {}

    return {"PostToolUse": [HookMatcher(matcher=None, hooks=[post])],
            "PostToolUseFailure": [HookMatcher(matcher=None, hooks=[post])]}


def block_domains(ctx: dict) -> dict:
    blocked = set((yaml.safe_load(BLOCKED_FILE.read_text(encoding="utf-8")) or {}).get("domains", [])) \
        if BLOCKED_FILE.exists() else set()

    async def pre(inp, tool_use_id, _context):
        host = urlparse((inp.get("tool_input") or {}).get("url", "")).hostname or ""
        if any(host == d or host.endswith("." + d) for d in blocked):
            return _deny(f"domínio bloqueado: {host}")
        return {}

    return {"PreToolUse": [HookMatcher(matcher="WebFetch", hooks=[pre])]}


def mcp_quota(ctx: dict, server: str) -> dict:
    from .data import get_router
    router = get_router()

    async def pre(inp, tool_use_id, _context):
        if not router.store.allow(server, router.limits(server)):
            return _deny(f"quota esgotada para {server}")
        router.store.record(server)
        return {}

    return {"PreToolUse": [HookMatcher(matcher=f"mcp__{server}__.*", hooks=[pre])]}


REGISTRY = {"log_tools": log_tools, "block_domains": block_domains, "mcp_quota": mcp_quota}


def build_hooks(entries: list, ctx: dict) -> dict:
    """Junta os hooks pedidos (mais log_tools) num dict {evento: [HookMatcher]}."""
    merged: dict[str, list] = {}
    for entry in ["log_tools", *[e for e in entries if e != "log_tools"]]:
        name, params = (entry, {}) if isinstance(entry, str) else (entry["name"], {k: v for k, v in entry.items() if k != "name"})
        for event, matchers in REGISTRY[name](ctx, **params).items():
            merged.setdefault(event, []).extend(matchers)
    return merged
