"""Carrega um pacote de agente (pasta em agents/<nome>/) para um AgentSpec."""
import importlib.util
import os
from dataclasses import dataclass, field
from pathlib import Path
from string import Template

import yaml
from pydantic import BaseModel

AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"


@dataclass
class AgentSpec:
    name: str
    path: Path
    description: str
    model: str | None
    max_turns: int
    inputs: list[str]
    tools: list[str]
    bash: list[str]
    mcp_servers: dict
    output_model: type[BaseModel]
    prompt_tpl: Template
    task_tpl: Template
    extra: dict = field(default_factory=dict)

    @property
    def allowed_tools(self) -> list[str]:
        return self.tools + [f"Bash({p})" for p in self.bash]


def _expand_env(obj):
    if isinstance(obj, str):
        return os.path.expandvars(obj)
    if isinstance(obj, dict):
        return {k: _expand_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env(v) for v in obj]
    return obj


def _load_class(agent_dir: Path, ref: str) -> type[BaseModel]:
    file, cls = ref.split(":")
    spec = importlib.util.spec_from_file_location(f"_agent_{agent_dir.name}_{Path(file).stem}", agent_dir / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, cls)


def load_agent(name: str) -> AgentSpec:
    d = AGENTS_DIR / name
    cfg = yaml.safe_load((d / "agent.yaml").read_text(encoding="utf-8"))
    return AgentSpec(
        name=cfg["name"],
        path=d,
        description=cfg.get("description", ""),
        model=cfg.get("model"),
        max_turns=cfg.get("max_turns", 20),
        inputs=cfg.get("inputs", []),
        tools=cfg.get("tools", []),
        bash=cfg.get("bash", []),
        mcp_servers=_expand_env(cfg.get("mcp_servers") or {}),
        output_model=_load_class(d, cfg["output"]),
        prompt_tpl=Template((d / "prompt.md").read_text(encoding="utf-8")),
        task_tpl=Template((d / "task.md").read_text(encoding="utf-8")),
    )
