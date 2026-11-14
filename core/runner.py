"""Executa um agente (pacote) com o Claude Agent SDK."""
import importlib
import inspect
import json
from datetime import datetime, timezone

import yaml
from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from .spec import AGENTS_DIR, load_agent


async def run_agent(name: str, **inputs):
    cfg = yaml.safe_load((AGENTS_DIR / name / "agent.yaml").read_text(encoding="utf-8"))
    if cfg.get("kind") == "script":  # agente de código, sem LLM: agents/<nome>/run.py -> run(**inputs)
        mod = importlib.import_module(f"agents.{name}.run")
        out = mod.run(**inputs)
        return await out if inspect.isawaitable(out) else out

    spec = load_agent(name)
    missing = [i for i in spec.inputs if i not in inputs]
    if missing:
        raise ValueError(f"{name}: faltam inputs {missing}")

    vars_ = {**inputs, "now": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    options = ClaudeAgentOptions(
        system_prompt=spec.prompt_tpl.safe_substitute(vars_),
        allowed_tools=spec.allowed_tools,
        mcp_servers=spec.mcp_servers,
        cwd=str(spec.path),             # scripts/templates relativos + .claude/skills da pasta
        setting_sources=["project"],    # carrega as skills do agente
        max_turns=spec.max_turns,
        model=spec.model,
        output_format={"type": "json_schema", "schema": spec.output_model.model_json_schema()},
    )

    async for msg in query(prompt=spec.task_tpl.safe_substitute(vars_), options=options):
        if isinstance(msg, ResultMessage):
            data = getattr(msg, "structured_output", None)
            if data is None:
                data = json.loads(msg.result)
            return spec.output_model.model_validate(data)
    raise RuntimeError(f"{name}: terminou sem resultado")
