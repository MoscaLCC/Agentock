"""Fase 10 — sessões LLM isoladas (D24): só o que é do agente entra no contexto; tokens gravados por nó."""
import tempfile
import textwrap
import unittest
from pathlib import Path

from core import db
from core.runner import AgentResult, _options, normalize_usage, persist
from core.spec import AGENTS_DIR, load_agent


def write(base: Path, rel: str, text: str) -> None:
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text), encoding="utf-8")


class IsolatedSessionTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        write(self.dir, "a/agent.yaml", """
            name: a
            model: claude-haiku-5-5
            tools: [WebSearch, Skill]
            bash: ["python scripts/*"]
            market_tools: [quote]
            inputs: [ticker]
        """)
        write(self.dir, "a/prompt.md", "Prompt de $ticker.")
        write(self.dir, "a/task.md", "Tarefa $ticker")
        write(self.dir, "a/.claude/skills/guia/SKILL.md", """\
            ---
            name: guia
            description: descrição que não deve ir para o prompt
            ---

            # Guia
            Regra com cifrão: nunca "$33B" nem $ticker.
        """)
        write(self.dir, "a/.claude/skills/guia/references/fontes.md", "Fonte local: KRX.\n")
        self.spec = load_agent("a", self.dir)
        self.opts = _options(self.spec, {"ticker": "AAPL"}, {"run_id": "teste-sessao", "agent": "a"})

    def test_only_declared_builtin_tools_are_available(self):
        # as 16 tools internas do Claude Code deixam de ir no contexto; Skill deixa de ser precisa
        self.assertEqual(self.opts.tools, ["WebSearch", "Bash"])
        self.assertNotIn("Skill", self.opts.allowed_tools)
        self.assertIn("Bash(python scripts/*)", self.opts.allowed_tools)
        self.assertIn("mcp__market__quote", self.opts.allowed_tools)

    def test_no_foreign_context(self):
        self.assertEqual(self.opts.skills, [])            # sem lista de skills globais
        self.assertTrue(self.opts.strict_mcp_config)       # sem conectores MCP da conta (Gmail, Drive…)
        self.assertEqual(self.opts.setting_sources, [])    # sem settings/CLAUDE.md do projeto
        self.assertEqual(self.opts.env.get("CLAUDE_CODE_DISABLE_AUTO_MEMORY"), "1")
        self.assertEqual(list(self.opts.mcp_servers), ["market"])

    def test_skill_is_inlined_in_system_prompt(self):
        sp = self.opts.system_prompt
        self.assertTrue(sp.startswith("Prompt de AAPL."))
        self.assertIn("# Guia", sp)
        self.assertIn("Fonte local: KRX.", sp)                       # referências da skill também
        self.assertNotIn("descrição que não deve ir", sp)            # front matter fora
        self.assertIn('nunca "$33B" nem $ticker', sp)                # o texto da skill não é um template

    def test_agent_without_tools_gets_no_builtin_tools(self):
        write(self.dir, "b/agent.yaml", "name: b\nmodel: claude-haiku-5-5\ntools: [Skill]\n")
        write(self.dir, "b/prompt.md", "p")
        write(self.dir, "b/task.md", "t")
        opts = _options(load_agent("b", self.dir), {}, {"run_id": "teste-sessao", "agent": "b"})
        self.assertEqual(opts.tools, [])
        self.assertEqual(opts.mcp_servers, {})

    def test_real_agents_do_not_ask_to_load_skills(self):
        for prompt in AGENTS_DIR.rglob("prompt.md"):
            self.assertNotIn("Carrega a skill", prompt.read_text(encoding="utf-8"), prompt)

    def test_real_llm_agents_inline_their_skill(self):
        for name, marker in (("technical_agent", "## Score"), ("rating_v1_agent", "# Rubrica de classificação"),
                             ("timing_agent", "timing"), ("forecast_agent", "enário")):
            spec = load_agent(name)
            self.assertIn(marker, spec.system_prompt({}), name)
            self.assertNotIn("Skill", spec.builtin_tools, name)


class UsageTests(unittest.TestCase):
    def test_normalize_usage_from_sdk_model_usage(self):
        mu = {"claude-opus-5-5": {"inputTokens": 4, "outputTokens": 1406, "cacheReadInputTokens": 23669,
                                  "cacheCreationInputTokens": 34086, "costUSD": 0.3056, "contextWindow": 200000}}
        self.assertEqual(normalize_usage(mu), {"claude-opus-5-5": {"input": 4, "cache_write": 34086,
                                                                   "cache_read": 23669, "output": 1406, "cost": 0.3056}})
        self.assertIsNone(normalize_usage(None))
        self.assertIsNone(normalize_usage({}))

    def test_usage_is_persisted_per_node(self):
        conn = db.connect(":memory:")
        usage = {"m": {"input": 1, "cache_write": 2, "cache_read": 3, "output": 4, "cost": 0.5}}
        persist(conn, "r1", "n1", "AAPL", AgentResult("x", "ok", {"a": 1}, cost_usd=0.5, turns=2, usage=usage))
        row = conn.execute("SELECT usage FROM agent_outputs WHERE run_id='r1'").fetchone()
        self.assertIn('"cache_write": 2', row["usage"])

    def test_old_database_gets_usage_column(self):
        path = Path(tempfile.mkdtemp()) / "old.db"
        import sqlite3
        c = sqlite3.connect(path)
        c.execute("CREATE TABLE agent_outputs (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, node TEXT,"
                  " agent TEXT NOT NULL, ticker TEXT, ts TEXT NOT NULL, status TEXT NOT NULL, cached INTEGER NOT NULL"
                  " DEFAULT 0, output TEXT, error TEXT, cost_usd REAL, duration_ms INTEGER, turns INTEGER)")
        c.commit()
        c.close()
        conn = db.connect(path)
        self.assertIn("usage", {r[1] for r in conn.execute("PRAGMA table_info(agent_outputs)")})
        conn.close()


if __name__ == "__main__":
    unittest.main()
