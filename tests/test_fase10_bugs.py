"""Fase 10 — bugs reproduzidos e corrigidos (cada teste falhava antes da correção)."""
import threading
import unittest
from datetime import datetime, timezone

from core import sessions


class CalendarRaceTests(unittest.TestCase):
    """asia_lead / europe_lead / us_lead correm em threads paralelas e criavam o mesmo calendário ao mesmo tempo:
    `ValueError: Length of values (70) does not match length of index (53)` (005930.KS, 2026-11-14)."""

    def test_market_state_is_thread_safe_on_first_use(self):
        from exchange_calendars import calendar_utils
        disp = calendar_utils.global_calendar_dispatcher
        now = datetime(2026, 11, 14, 17, 6, 35, tzinfo=timezone.utc)
        for code in ("XKRX", "XTKS"):
            disp._calendars.pop(code, None)             # força a construção de raiz, como num processo novo
            disp._factory_output_cache.pop(code, None)
            getattr(sessions, "_CALENDARS", {}).pop(code, None)
            errors, results = [], []
            barrier = threading.Barrier(4)

            def worker():
                barrier.wait()
                try:
                    results.append(sessions.market_state(code, now))
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{type(e).__name__}: {e}")

            threads = [threading.Thread(target=worker) for _ in range(4)]
            [t.start() for t in threads]
            [t.join() for t in threads]
            self.assertEqual(errors, [], code)
            self.assertEqual(len({r["last_close"] for r in results}), 1)
        self.assertEqual(results[0]["last_close"], "2026-11-13T06:30:00+00:00")  # sexta-feira, fecho de Tóquio


if __name__ == "__main__":
    unittest.main()
