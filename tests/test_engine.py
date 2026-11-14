import asyncio
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

from core import db
from core.hooks import build_hooks
from core.orchestrator import Node, layers, load_flow, resolve, run_flow
from core.runner import AgentResult
from core.spec import load_agent


def write(base: Path, rel: str, text: str) -> None:
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text), encoding="utf-8")


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        # agente LLM base + filho que herda (não é executado; só testa o loader)
        write(self.dir, "_shared/base/agent.yaml", """
            name: base
            model: claude-sonnet-5-5
            max_turns: 7
            tools: [WebSearch]
            inputs: [ticker]
            output: schema.py:Out
        """)
        write(self.dir, "_shared/base/prompt.md", "prompt base $hours")
        write(self.dir, "_shared/base/task.md", "task $ticker")
        write(self.dir, "_shared/base/schema.py", "from pydantic import BaseModel\nclass Out(BaseModel):\n    x: int\n")
        write(self.dir, "_shared/base/scripts/s.py", "")
        write(self.dir, "child/agent.yaml", "name: child\nextends: _shared/base\nmax_turns: 3\n")
        # agentes script para o orquestrador
        write(self.dir, "double/agent.yaml", "name: double\nkind: script\ninputs: [n]\ncache_ttl: 600\n")
        write(self.dir, "double/run.py", "def run(n):\n    return {'value': n * 2}\n")
        write(self.dir, "add/agent.yaml", "name: add\nkind: script\ninputs: [a, b]\n")
        write(self.dir, "add/run.py", "def run(a, b):\n    return {'value': (a or 0) + (b or 0)}\n")
        write(self.dir, "boom/agent.yaml", "name: boom\nkind: script\n")
        write(self.dir, "boom/run.py", "def run():\n    raise ValueError('falhou de propósito')\n")
        write(self.dir, "slow/agent.yaml", "name: slow\nkind: script\n")
        write(self.dir, "slow/run.py", "import asyncio\nasync def run():\n    await asyncio.sleep(5)\n")
        self.conn = db.connect(":memory:")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def flow(self, spec, params, **kw):
        return asyncio.run(run_flow(spec, params, conn=self.conn, agents_dir=self.dir, **kw))

    # ---- loader
    def test_extends_merges_and_finds_parent_files(self):
        s = load_agent("child", self.dir)
        self.assertEqual((s.max_turns, s.model, s.tools), (3, "claude-sonnet-5-5", ["WebSearch"]))
        self.assertEqual(s.prompt_tpl.safe_substitute(hours=4), "prompt base 4")
        self.assertEqual(s.output_model.__name__, "Out")
        self.assertEqual(s.asset_dir, self.dir / "_shared" / "base")

    def test_circular_extends(self):
        write(self.dir, "x/agent.yaml", "name: x\nextends: y\n")
        write(self.dir, "y/agent.yaml", "name: y\nextends: x\n")
        with self.assertRaises(ValueError):
            load_agent("x", self.dir)

    # ---- DAG
    def test_layers_from_references(self):
        nodes = load_flow({"a": {"agent": "double", "inputs": {"n": "$n"}},
                           "b": {"agent": "double", "inputs": {"n": "$a.value"}},
                           "c": {"agent": "add", "inputs": {"a": "$a.value", "b": "$b.value"}}})
        self.assertEqual(layers(nodes), [["a"], ["b"], ["c"]])

    def test_cycle_detected(self):
        nodes = {"a": Node("a", "x", {"v": "$b"}), "b": Node("b", "x", {"v": "$a"})}
        with self.assertRaises(ValueError):
            layers(nodes)

    def test_resolve_paths(self):
        results = {"a": AgentResult("a", "ok", {"k": {"z": 5}}), "f": AgentResult("f", "failed")}
        self.assertEqual(resolve({"x": "$a.k.z", "y": "$t", "w": "$f", "lit": "texto"}, {"t": 1}, results),
                         {"x": 5, "y": 1, "w": None, "lit": "texto"})

    # ---- execução
    def test_flow_runs_and_chains(self):
        rep = self.flow({"a": {"agent": "double", "inputs": {"n": "$n"}},
                         "b": {"agent": "double", "inputs": {"n": "$a.value"}}}, {"n": 3})
        self.assertEqual(rep.results["b"].output, {"value": 12})
        rows = self.conn.execute("SELECT node, status FROM agent_outputs WHERE run_id=?", (rep.run_id,)).fetchall()
        self.assertEqual(sorted(tuple(r) for r in rows), [("a", "ok"), ("b", "ok")])

    def test_failure_is_isolated(self):
        rep = self.flow({"boom": {"agent": "boom"},
                         "after": {"agent": "add", "inputs": {"a": "$boom.value", "b": 1}}}, {})
        self.assertEqual(rep.results["boom"].status, "failed")
        self.assertIn("falhou de propósito", rep.results["boom"].error)
        self.assertEqual(rep.results["after"].output, {"value": 1})

    def test_timeout(self):
        rep = self.flow({"slow": {"agent": "slow", "timeout": 0.2}}, {})
        self.assertEqual(rep.results["slow"].status, "failed")
        self.assertIn("timeout", rep.results["slow"].error)

    def test_output_cache(self):
        spec = {"a": {"agent": "double", "inputs": {"n": "$n"}}}
        self.assertFalse(self.flow(spec, {"n": 5}).results["a"].cached)
        second = self.flow(spec, {"n": 5}).results["a"]
        self.assertTrue(second.cached)
        self.assertEqual(second.output, {"value": 10})
        self.assertFalse(self.flow(spec, {"n": 5}, use_cache=False).results["a"].cached)

    def test_missing_input(self):
        rep = self.flow({"a": {"agent": "double"}}, {})
        self.assertIn("faltam inputs", rep.results["a"].error)

    # ---- hooks
    def test_hooks_block_domain(self):
        hooks = build_hooks(["block_domains"], {"run_id": "test", "agent": "t"})
        self.assertIn("PreToolUse", hooks)
        pre = hooks["PreToolUse"][0].hooks[0]
        out = asyncio.run(pre({"tool_input": {"url": "https://www.gurufocus.com/x"}}, None, None))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(asyncio.run(pre({"tool_input": {"url": "https://reuters.com/x"}}, None, None)), {})


if __name__ == "__main__":
    unittest.main()
