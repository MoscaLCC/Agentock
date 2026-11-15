import unittest

from core import db
from core.changes import evaluate
from core.ratings import Rating as R
from agents.change_alert_agent.run import run as alert_run
from core.schemas import Synthesis


class Capture:
    def __init__(self):
        self.sent = []

    def send(self, text, html=False):
        self.sent.append(text)
        return True


class ChangeTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_first_observation_sets_baseline_no_alert(self):
        self.assertIsNone(evaluate(self.conn, "X", R.BUY))

    def test_same_rating_no_change(self):
        evaluate(self.conn, "X", R.BUY)
        self.assertIsNone(evaluate(self.conn, "X", R.BUY))

    def test_big_jump_is_immediate(self):
        evaluate(self.conn, "X", R.HOLD)
        c = evaluate(self.conn, "X", R.STRONG_BUY)
        self.assertEqual((c.kind, c.delta), ("immediate", 2))

    def test_one_level_needs_two_consecutive_runs(self):
        evaluate(self.conn, "X", R.HOLD, ts="2026-11-14T09:00:00+00:00")
        self.assertIsNone(evaluate(self.conn, "X", R.BUY, ts="2026-11-14T10:00:00+00:00"))   # 1.ª vez: pendente
        c = evaluate(self.conn, "X", R.BUY, ts="2026-11-14T16:00:00+00:00")                   # 2.ª: confirma
        self.assertEqual((c.kind, c.old, c.new), ("confirmed", R.HOLD, R.BUY))

    def test_same_observation_again_is_not_a_confirmation(self):
        """A7 — um retry, uma retoma ou uma reanálise minutos depois confirmavam uma mudança de 1 nível."""
        evaluate(self.conn, "X", R.HOLD, ts="2026-11-14T09:00:00+00:00", run_id="r0")
        self.assertIsNone(evaluate(self.conn, "X", R.BUY, ts="2026-11-14T10:00:00+00:00", run_id="r1"))
        self.assertIsNone(evaluate(self.conn, "X", R.BUY, ts="2026-11-14T10:00:05+00:00", run_id="r1"))  # mesma análise
        self.assertIsNone(evaluate(self.conn, "X", R.BUY, ts="2026-11-14T10:20:00+00:00", run_id="r2"))  # 20 min depois
        c = evaluate(self.conn, "X", R.BUY, ts="2026-11-14T15:00:00+00:00", run_id="r3")                  # 5 h depois
        self.assertEqual(c.kind, "confirmed")

    def test_same_run_never_alerts_twice(self):
        evaluate(self.conn, "X", R.HOLD, run_id="r0")
        self.assertEqual(evaluate(self.conn, "X", R.STRONG_BUY, run_id="r1").kind, "immediate")
        self.assertIsNone(evaluate(self.conn, "X", R.STRONG_BUY, run_id="r1"))

    def test_flip_flop_does_not_alert(self):
        evaluate(self.conn, "X", R.HOLD)
        for r in (R.BUY, R.HOLD, R.BUY, R.HOLD):
            self.assertIsNone(evaluate(self.conn, "X", r))

    def test_alert_agent_sends_and_logs(self):
        n = Capture()
        mk = lambda r: Synthesis(ticker="X", rating=r, confidence=0.8, price=10.0, reasons=["a"])
        alert_run(mk("hold"), conn=self.conn, notifier=n)
        out = alert_run(mk("strong_buy"), conn=self.conn, notifier=n)
        self.assertTrue(out["changed"] and out["sent"])
        self.assertIn("HOLD → COMPRA FORTE", n.sent[0])
        self.assertIn("/detalhe_X", n.sent[0])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0], 1)

    def test_history_saved(self):
        from agents.memory_agent.run import run as mem_run
        mem_run(Synthesis(ticker="X", rating="buy", confidence=0.5), conn=self.conn)
        self.assertEqual(db.history(self.conn, "X")[0]["rating"], 1)

    def test_memory_is_idempotent_per_run(self):
        """A7 — gravar duas vezes a mesma análise (retry, retoma) duplicava o histórico."""
        from agents.memory_agent.run import run as mem_run
        s = Synthesis(ticker="X", rating="buy", confidence=0.5, run_id="run-1")
        first = mem_run(s, conn=self.conn)
        second = mem_run(s, conn=self.conn)
        self.assertEqual(first["saved_id"], second["saved_id"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1)

    def test_alert_is_recorded_before_sending_and_can_be_deferred(self):
        n = Capture()
        mk = lambda r, rid: Synthesis(ticker="X", rating=r, confidence=0.8, price=10.0, reasons=["a"], run_id=rid)
        alert_run(mk("hold", "a"), conn=self.conn, notifier=n)
        out = alert_run(mk("strong_buy", "b"), conn=self.conn, notifier=n, notify=False)   # o bot mostra o cartão
        self.assertTrue(out["changed"] and out["deferred"] and not out["sent"])
        self.assertEqual(n.sent, [])
        row = self.conn.execute("SELECT sent, run_id FROM alerts").fetchone()
        self.assertEqual((row["sent"], row["run_id"]), (0, "b"))


if __name__ == "__main__":
    unittest.main()
