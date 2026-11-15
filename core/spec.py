"""Carrega um pacote de agente (agents/<nome>/agent.yaml) para um AgentSpec.

Campos do agent.yaml:
  name, description, kind (llm | script), extends (ex.: _shared/news_base)
  model, effort, max_turns, max_budget_usd
  inputs, output (ficheiro.py:Classe)
  tools, bash, mcp_servers, market_tools (tools do router expostas ao LLM)
  hooks (nomes ou {name, ...}), subagents ({nome: {description, prompt (ficheiro), tools, model}})
  cache_ttl (segundos; 0 = sem cache), cache_key (inputs que definem a chave; omisso = todos)
  defaults (valores por omissão dos inputs)
  file_inputs (inputs também gravados em data/runs/<run_id>/<agente>/<nome>.json → variável $<nome>_file;
               a pasta fica acessível ao agente e aos subagentes)
  mcp_servers.<nome>.requires_env: o MCP só fica ativo se essas variáveis existirem

Herança: o filho sobrepõe-se ao pai campo a campo; ficheiros (prompt.md, task.md, schema, subagentes)
procuram-se primeiro na pasta do filho e depois nas dos antepassados.
"""
import importlib.util
import os
from dataclasses import dataclass, field
from pathlib import Path
from string import Template

import yaml
from pydantic import BaseModel

AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"
ASSET_MARKERS = (".claude", "scripts", "templates")


@dataclass
class AgentSpec:
    name: str
    path: Path
    dirs: list[Path]
    kind: str = "llm"
    description: str = ""
    model: str | None = None
    effort: str | None = None
    max_turns: int = 20
    max_budget_usd: float | None = None
    inputs: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    bash: list[str] = field(default_factory=list)
    mcp_servers: dict = field(default_factory=dict)
    market_tools: list[str] = field(default_factory=list)
    hooks: list = field(default_factory=list)
    subagents: dict = field(default_factory=dict)
    cache_ttl: int = 0
    cache_key: list[str] | None = None
    defaults: dict = field(default_factory=dict)
    file_inputs: list[str] = field(default_factory=list)
    output_model: type[BaseModel] | None = None
    prompt_tpl: Template | None = None
    task_tpl: Template | None = None
    raw: dict = field(default_factory=dict)

    @property
    def asset_dir(self) -> Path:
        """Pasta usada como cwd do agente: a primeira (filho → pai) com skills/scripts/templates."""
        for d in self.dirs:
            if any((d / m).exists() for m in ASSET_MARKERS):
                return d
        return self.path

    @property
    def builtin_tools(self) -> list[str]:
        """Tools internas que ficam DISPONÍVEIS na sessão (D24): só as declaradas. Sem isto, as 16 tools do
        Claude Code (~10 mil tokens de definições) vão em todos os pedidos. `Skill` não entra: as skills do agente
        são coladas no system prompt (ver `skills_text`)."""
        tools = [t for t in self.tools if t != "Skill"]
        if self.bash and "Bash" not in tools:
            tools.append("Bash")
        if self.subagents and "Agent" not in tools:
            tools.append("Agent")
        return tools

    @property
    def allowed_tools(self) -> list[str]:
        tools = [t for t in self.builtin_tools if t != "Bash"] + [f"Bash({p})" for p in self.bash]
        return tools + [f"mcp__market__{t}" for t in self.market_tools]

    @property
    def skills_text(self) -> str:
        """Skills do agente (filho → antepassados), sem front matter, com as suas referências.
        Vão no system prompt: poupa um pedido inteiro à API por agente e a lista de skills globais."""
        out, seen = [], set()
        for d in self.dirs:
            for skill in sorted((d / ".claude" / "skills").glob("*/SKILL.md")):
                name = skill.parent.name
                if name in seen:
                    continue
                seen.add(name)
                body = skill.read_text(encoding="utf-8")
                if body.startswith("---"):
                    body = body.split("---", 2)[-1]
                out.append(f"---\nGuia `{name}`:\n\n{body.strip()}")
                for ref in sorted((skill.parent / "references").glob("*.md")):
                    out.append(f"### references/{ref.name}\n\n{ref.read_text(encoding='utf-8').strip()}")
        return "\n\n".join(out)

    @property
    def single_request(self) -> bool:
        """Agente sem tools: a sessão faz um único pedido à API (lê o prompt, devolve o output estruturado)."""
        return not (self.builtin_tools or self.market_tools or self.mcp_servers or self.subagents)

    @property
    def session_env(self) -> dict[str, str]:
        """Variáveis do processo do agente (medido em 2026-11-15, ver docs/BASELINE.md e PLANO D24):
        - sem memória do Claude Code do projeto no contexto;
        - sem a chamada extra ao Haiku para dar título à sessão (levava o prompt inteiro);
        - sem cache de prompt quando há um só pedido: a escrita em cache custa 2× o input e nunca é lida."""
        env = {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "CLAUDE_CODE_DISABLE_TERMINAL_TITLE": "1"}
        if self.single_request:
            env["DISABLE_PROMPT_CACHING"] = "1"
        return env

    def system_prompt(self, vars_: dict) -> str:
        """Prompt do agente com as variáveis substituídas + guias (estes não são template: podem ter '$')."""
        text = self.prompt_tpl.safe_substitute(vars_)
        return f"{text.rstrip()}\n\n{self.skills_text}" if self.skills_text else text

    def find(self, rel: str) -> Path | None:
        for d in self.dirs:
            if (d / rel).exists():
                return d / rel
        return None

    def read(self, rel: str) -> str:
        p = self.find(rel)
        if p is None:
            raise FileNotFoundError(f"{self.name}: {rel} não encontrado em {[str(d) for d in self.dirs]}")
        return p.read_text(encoding="utf-8")


def _active_mcp(servers: dict) -> dict:
    """MCPs com `requires_env: [VAR]` só ficam ativos se todas as variáveis existirem."""
    out = {}
    for name, cfg in (servers or {}).items():
        cfg = dict(cfg)
        if all(os.environ.get(v) for v in cfg.pop("requires_env", [])):
            out[name] = cfg
    return out


def _expand_env(obj):
    if isinstance(obj, str):
        return os.path.expandvars(obj)
    if isinstance(obj, dict):
        return {k: _expand_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env(v) for v in obj]
    return obj


def _load_chain(name: str, agents_dir: Path, seen: tuple = ()) -> tuple[dict, list[Path]]:
    if name in seen:
        raise ValueError(f"herança circular: {' -> '.join(seen + (name,))}")
    d = agents_dir / name
    cfg = yaml.safe_load((d / "agent.yaml").read_text(encoding="utf-8")) or {}
    parent = cfg.pop("extends", None)
    if not parent:
        return cfg, [d]
    pcfg, pdirs = _load_chain(parent, agents_dir, seen + (name,))
    return {**pcfg, **cfg}, [d] + pdirs


def _load_class(path: Path, cls: str, tag: str) -> type[BaseModel]:
    spec = importlib.util.spec_from_file_location(f"_agent_{tag}_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, cls)


def read_config(name: str, agents_dir: Path | None = None) -> dict:
    return _load_chain(name, agents_dir or AGENTS_DIR)[0]


def load_agent(name: str, agents_dir: Path | None = None) -> AgentSpec:
    agents_dir = agents_dir or AGENTS_DIR
    cfg, dirs = _load_chain(name, agents_dir)
    spec = AgentSpec(
        name=cfg.get("name", name), path=dirs[0], dirs=dirs, kind=cfg.get("kind", "llm"),
        description=cfg.get("description", ""), model=cfg.get("model"), effort=cfg.get("effort"),
        max_turns=cfg.get("max_turns", 20), max_budget_usd=cfg.get("max_budget_usd"),
        inputs=cfg.get("inputs", []) or [], tools=cfg.get("tools", []) or [], bash=cfg.get("bash", []) or [],
        mcp_servers=_expand_env(_active_mcp(cfg.get("mcp_servers"))), market_tools=cfg.get("market_tools", []) or [],
        hooks=cfg.get("hooks", []) or [], subagents=cfg.get("subagents") or {},
        cache_ttl=int(cfg.get("cache_ttl", 0) or 0), cache_key=cfg.get("cache_key"),
        defaults=cfg.get("defaults") or {}, file_inputs=cfg.get("file_inputs") or [], raw=cfg,
    )
    if cfg.get("output"):
        file, cls = cfg["output"].split(":")
        p = spec.find(file)
        if p is None:
            raise FileNotFoundError(f"{name}: {file} não encontrado")
        spec.output_model = _load_class(p, cls, spec.name)
    if spec.kind == "llm":
        spec.prompt_tpl = Template(spec.read("prompt.md"))
        spec.task_tpl = Template(spec.read("task.md"))
    return spec
