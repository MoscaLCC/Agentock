"""Fase 10 — escalonamento por dependências, progresso, cancelamento e nós condicionais."""
import asyncio
import shutil
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from core import db
from core.orchestrator import run_flow


def write(base: Path, rel: str, text: str) -> None:
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text), encoding="utf-8")


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        write(self.dir, "wait/agent.yaml", "name: wait\nkind: script\ndefaults: {secs: 0, dep: null, tag: x}\n")
        write(self.dir, "wait/run.py", """
            import asyncio, time
            async def run(secs=0, dep=None, tag="x"):
                await asyncio.sleep(secs)
                return {"tag": tag, "t": time.time()}
        """)
        write(self.dir, "boom/agent.yaml", "name: boom\nkind: script\n")
        write(self.dir, "boom/run.py", "def run():\n    raise ValueError('falhou')\n")
        self.conn = db.connect(":memory:")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def flow(self, spec, params=None, **kw):
        return asyncio.run(run_flow(spec, params or {}, conn=self.conn, agents_dir=self.dir, **kw))

    def test_node_starts_when_its_dependencies_finish_not_when_the_layer_does(self):
        # 'lento' e 'rapido' estão na mesma camada; 'depois' só depende de 'rapido' e não pode esperar por 'lento'
        spec = {"lento": {"agent": "wait", "inputs": {"secs": 0.6}},
                "rapido": {"agent": "wait", "inputs": {"secs": 0.05}},
                "depois": {"agent": "wait", "inputs": {"dep": "$rapido", "secs": 0.05}},
                "fim": {"agent": "wait", "inputs": {"dep": "$depois", "tag": "$lento.tag"}}}
        t0 = time.time()
        rep = self.flow(spec)
        total = time.time() - t0
        self.assertLess(rep.results["depois"].output["t"], rep.results["lento"].output["t"])
        self.assertLess(total, 0.95)                      # ≈ 0,6 s (caminho crítico), não 0,6 + 0,05 + 0,05 em série
        self.assertEqual(rep.results["fim"].output["tag"], "x")
        self.assertEqual(list(rep.results), ["lento", "rapido", "depois", "fim"])   # ordem estável (a do fluxo)
        self.assertGreater(rep.duration_s, 0.5)

    def test_progress_events(self):
        events = []
        spec = {"a": {"agent": "wait"}, "b": {"agent": "boom"}, "c": {"agent": "wait", "inputs": {"dep": "$a"}}}
        self.flow(spec, on_event=events.append)
        starts = [e["node"] for e in events if e["type"] == "start"]
        dones = {e["node"]: e for e in events if e["type"] == "done"}
        self.assertEqual(sorted(starts), ["a", "b", "c"])
        self.assertEqual((dones["a"]["status"], dones["b"]["status"]), ("ok", "failed"))
        self.assertEqual(sorted(e["done"] for e in dones.values()), [1, 2, 3])
        self.assertTrue(all(e["total"] == 3 for e in events))

    def test_event_handler_errors_do_not_break_the_run(self):
        def bad(_e):
            raise RuntimeError("o Telegram caiu")
        rep = self.flow({"a": {"agent": "wait"}}, on_event=bad)
        self.assertEqual(rep.results["a"].status, "ok")

    def test_cancel_stops_running_and_pending_nodes(self):
        async def go():
            cancel = asyncio.Event()
            spec = {"a": {"agent": "wait", "inputs": {"secs": 5}},
                    "b": {"agent": "wait", "inputs": {"dep": "$a"}}}
            task = asyncio.create_task(run_flow(spec, {}, conn=self.conn, agents_dir=self.dir, cancel=cancel))
            await asyncio.sleep(0.1)
            cancel.set()
            return await asyncio.wait_for(task, 2)
        t0 = time.time()
        rep = asyncio.run(go())
        self.assertLess(time.time() - t0, 2)
        self.assertTrue(rep.cancelled)
        self.assertEqual({r.status for r in rep.results.values()}, {"cancelled"})
        rows = self.conn.execute("SELECT node, status FROM agent_outputs WHERE run_id=?", (rep.run_id,)).fetchall()
        self.assertEqual(sorted(tuple(r) for r in rows), [("a", "cancelled"), ("b", "cancelled")])

    def test_conditional_node_is_off_without_being_a_failure(self):
        spec = {"defaults": {"debate": True},
                "nodes": {"bull": {"agent": "wait", "when": "$debate", "inputs": {"tag": "bull"}},
                          "juiz": {"agent": "wait", "inputs": {"dep": "$bull", "tag": "$bull.tag"}}}}
        on = self.flow(spec)
        self.assertEqual(on.results["juiz"].output["tag"], "bull")
        off = self.flow(spec, {"debate": False})
        self.assertEqual(off.results["bull"].status, "off")
        self.assertEqual(off.results["juiz"].status, "ok")        # o dependente corre com esse input a None
        self.assertEqual(off.problems(), {})                       # um nó desligado não é uma falha
        self.assertEqual(list(self.flow({"b": {"agent": "boom"}}).problems()), ["b"])


if __name__ == "__main__":
    unittest.main()
