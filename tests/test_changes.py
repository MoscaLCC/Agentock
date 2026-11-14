import unittest

from core import db
from core.changes import evaluate
from core.ratings import Rating as R
from agents.change_alert_agent.run import run as alert_run
from core.schemas import Synthesis


class Capture:
    def __init__(self):
        self.sent = []

    def send(self, text):
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
        evaluate(self.conn, "X", R.HOLD)
        self.assertIsNone(evaluate(self.conn, "X", R.BUY))      # 1.ª vez: pendente
        c = evaluate(self.conn, "X", R.BUY)                      # 2.ª: confirma
        self.assertEqual((c.kind, c.old, c.new), ("confirmed", R.HOLD, R.BUY))

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
        self.assertIn("Hold -> Compra forte", n.sent[0])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0], 1)

    def test_history_saved(self):
        from agents.memory_agent.run import run as mem_run
        mem_run(Synthesis(ticker="X", rating="buy", confidence=0.5), conn=self.conn)
        self.assertEqual(db.history(self.conn, "X")[0]["rating"], 1)


if __name__ == "__main__":
    unittest.main()
