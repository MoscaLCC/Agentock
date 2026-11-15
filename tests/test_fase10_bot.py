"""Fase 10 — bot Telegram: fila persistente, progresso, cancelamento, retoma, erros humanos, robustez da API.
Tudo offline: API do Telegram falsa e fluxo falso (nenhuma análise real, nenhuma mensagem enviada)."""
import asyncio
import io
import json
import time
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone

from core import db, errors, jobs, messages as M, telegram
from core.orchestrator import RunReport
from core.progress import Progress
from core.runner import AgentResult, new_run_id
from tools import telegram_bot as tb


class FakeAPI:
    """Regista o que o bot enviaria."""
    chat_id = "42"

    def __init__(self):
        self.sent, self.edits, self.photos, self.answers, self.calls = [], [], [], [], []
        self.next_id = 100
        self.fail_edit = False

    def redact(self, x):
        return str(x)

    def send_message(self, text, html=False, buttons=None):
        self.next_id += 1
        self.sent.append({"id": self.next_id, "text": text, "buttons": buttons})
        return {"message_id": self.next_id}

    def edit_message(self, message_id, text, html=False, buttons=None):
        if self.fail_edit:
            return False
        self.edits.append({"id": message_id, "text": text, "buttons": buttons})
        return True

    def send_photo(self, png, caption="", html=False, buttons=None):
        self.next_id += 1
        self.photos.append({"id": self.next_id, "caption": caption, "buttons": buttons})
        return {"message_id": self.next_id}

    def chat_action(self, action="typing"):
        pass

    def answer_callback(self, callback_id, text=""):
        self.answers.append(callback_id)

    def call(self, method, http_timeout=60, **params):
        self.calls.append((method, params))
        return {"ok": True, "result": []}

    def all_text(self) -> str:
        return "\n".join(m["text"] for m in self.sent + self.edits)

    def labels(self, msg) -> list[str]:
        return [b["text"] for row in (msg.get("buttons") or {}).get("inline_keyboard", []) for b in row]

    def callbacks(self, msg) -> list[str]:
        return [b["callback_data"] for row in (msg.get("buttons") or {}).get("inline_keyboard", []) for b in row]


def msg(text, uid=1, date=None, chat=42, sender=42, chat_type="private"):
    return {"update_id": uid, "message": {"text": text, "date": date if date is not None else time.time(),
                                          "chat": {"id": chat, "type": chat_type}, "from": {"id": sender}}}


def tap(data, uid=50, message_id=7, text=None, chat=42, sender=42):
    m = {"message_id": message_id, "chat": {"id": chat, "type": "private"}}
    if text:
        m["text"] = text
    return {"update_id": uid, "callback_query": {"id": "cb", "data": data, "from": {"id": sender}, "message": m}}


class BotCase(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.api = FakeAPI()
        self.flows = []

    def bot(self, runner=None):
        async def default(flow, params, **kw):
            self.flows.append((flow, params, kw))
            return self.ok_report(params, kw)
        return tb.Bot(self.api, self.conn, runner=runner or default)

    def ok_report(self, params, kw, rating="buy", extra=None):
        """Simula uma análise completa: grava a classificação e devolve o relatório."""
        from agents.memory_agent.run import run as mem
        from core.schemas import Synthesis
        rid = kw["run_id"]
        prof = {"symbol": "AAPL", "name": "Apple Inc.", "price": 356.4, "currency": "USD", "change_pct": 0.44}
        db.save_agent_output(self.conn, run_id=rid, node="profile", agent="profile_agent", ticker="AAPL", status="ok",
                             cached=False, output=json.dumps(prof), error=None, cost_usd=0, duration_ms=10, turns=0)
        mem(Synthesis(ticker="AAPL", rating=rating, confidence=0.6, price=356.4, currency="USD", run_id=rid,
                      headline="Empresa excelente, mas o preço já desconta o bom momento", reasons=["Razão: 9/9"]),
            conn=self.conn)
        results = {"profile": AgentResult("profile_agent", "ok", prof), "guard": AgentResult("guard_agent", "ok", {}),
                   "alert": AgentResult("change_alert_agent", "ok", {"changed": False}), **(extra or {})}
        for e in ({"type": "start", "node": "profile"}, {"type": "done", "node": "profile", "status": "ok"}):
            kw["on_event"](e)
        return RunReport(rid, [list(results)], results, duration_s=1.0)

    def run_all(self, bot, *updates, work=True):
        async def go():
            for u in updates:
                await bot.on_update(u)
            await bot.flush_stale()
            while work and (job := jobs.claim(self.conn)):
                await bot.run_job(job)
        asyncio.run(go())


class AnalyseTests(BotCase):
    def test_analysis_edits_one_status_message_into_the_verdict_and_sends_the_card(self):
        bot = self.bot()
        self.run_all(bot, msg("/analisar AAPL"))
        self.assertEqual(len(self.api.sent), 1)                                   # 1.ª resposta: uma só mensagem
        self.assertIn("A analisar AAPL", self.api.sent[0]["text"])
        self.assertEqual(self.api.labels(self.api.sent[0]), ["✖️ Cancelar"])
        final = self.api.edits[-1]
        self.assertEqual(final["id"], self.api.sent[0]["id"])                     # a mesma mensagem vira veredicto
        self.assertIn("Apple — COMPRA", final["text"])
        self.assertIn("confiança 60%", final["text"])
        self.assertIn("356,40 USD (+0,44% hoje)", final["text"])
        self.assertLessEqual(len(final["text"]), 400)
        self.assertEqual(len(self.api.photos), 1)
        self.assertIn("🔁 Reanalisar", self.api.labels(self.api.photos[0]))
        job = jobs.recent(self.conn, 1)[0]
        self.assertEqual(job["state"], "done")
        self.assertEqual(self.flows[0][1]["alert_notify"], False)                 # sem 2.º cartão do nó de alerta
        self.assertEqual(self.flows[0][1]["debate"], True)

    def test_free_text_asks_before_spending(self):
        bot = self.bot()
        self.run_all(bot, msg("Banco Comercial"))
        self.assertIn("Analisar <b>Banco Comercial</b>?", self.api.sent[0]["text"])
        self.assertEqual(jobs.active(self.conn), [])                              # ainda nada em fila
        yes = self.api.callbacks(self.api.sent[0])[0]
        self.run_all(bot, tap(yes))
        self.assertEqual(self.flows[0][1]["ticker"], "Banco Comercial")
        self.run_all(bot, tap(yes, uid=51))                                       # 2.º toque no mesmo botão
        self.assertEqual(len(self.flows), 1)
        self.assertIn("já foi tratado", self.api.all_text())

    def test_arguments_and_tappable_commands(self):
        bot = self.bot()
        self.run_all(bot, msg("/run Banco Comercial V1"), work=False)
        job = jobs.active(self.conn)[0]
        self.assertEqual((job["args"]["query"], job["args"]["version"]), ("Banco Comercial", "v1"))
        self.assertEqual(tb.Bot.parse("/analisar_005930_KS"), ("analisar", ["005930.KS"]))
        self.assertEqual(tb.Bot.parse("/detalhe_AAPL@AgentockBot"), ("detalhe", ["AAPL"]))
        self.assertEqual(tb.Bot.parse("/hoje"), ("hoje", []))

    def test_invalid_input_never_reaches_the_flow(self):
        bot = self.bot()
        for bad in ("/analisar a:b", "/analisar a*b?", "/analisar " + "x" * 300, "/analisar ../../x", "/analisar"):
            self.run_all(bot, msg(bad))
        self.assertEqual(self.flows, [])
        self.assertEqual(jobs.active(self.conn), [])
        self.assertRegex(new_run_id("a:b*c?/..\\" + "z" * 300), r"^\d{8}T\d{6}-[A-Za-z0-9_-]{1,24}-[0-9a-f]{6}$")

    def test_duplicate_request_and_duplicate_update_do_not_run_twice(self):
        bot = self.bot()
        self.run_all(bot, msg("/analisar AAPL", uid=1), msg("/analisar aapl", uid=2), msg("/analisar AAPL", uid=1), work=False)
        self.assertEqual(len(jobs.active(self.conn)), 1)
        self.assertIn("já está em fila", self.api.all_text())
        self.run_all(bot)
        self.assertEqual(len(self.flows), 1)

    def test_only_the_owner_is_obeyed(self):
        bot = self.bot()
        self.run_all(bot, msg("/analisar AAPL", chat=999, sender=999), tap("r|AAPL", chat=999, sender=999),
                     msg("/analisar AAPL", chat=42, sender=7, chat_type="group"))
        self.assertEqual((self.api.sent, self.flows), ([], []))

    def test_stale_commands_are_not_executed_blindly(self):
        """A6 — com o bot desligado, os /run antigos eram todos executados no arranque (análises pagas em duplicado)."""
        bot = self.bot()
        old = time.time() - 3600
        self.run_all(bot, msg("/analisar AAPL", uid=1, date=old), msg("/estado", uid=2, date=old))
        self.assertEqual(self.flows, [])
        self.assertIn("Estive desligado", self.api.sent[0]["text"])
        self.assertEqual(len(self.api.callbacks(self.api.sent[0])), 1)            # só o pedido de análise pode repetir-se
        self.assertEqual(jobs.kv_get(self.conn, "tg_offset"), 3)                  # o offset fica gravado
        self.run_all(bot, tap(self.api.callbacks(self.api.sent[0])[0]))
        self.assertEqual(len(self.flows), 1)


class FailureTests(BotCase):
    def failing(self, results):
        async def runner(flow, params, **kw):
            self.flows.append((flow, params, kw))
            return RunReport(kw["run_id"], [list(results)], results)
        return runner

    def test_ambiguous_ticker_offers_buttons(self):
        err = "ValueError: 'ABC' é ambíguo — escolhe uma: Alpha Co → ABC.F; Beta KK → 2670.T"
        bot = self.bot(self.failing({"profile": AgentResult("profile_agent", "failed", error=err)}))
        self.run_all(bot, msg("/analisar ABC"))
        final = self.api.edits[-1]
        self.assertIn("pode ser 2 empresas", final["text"])
        self.assertEqual(self.api.callbacks(final), ["r|ABC.F", "r|2670.T"])
        self.assertNotIn("ValueError", final["text"])

    def test_unknown_ticker_is_explained_without_exception_names(self):
        err = "ValueError: não encontrei nenhuma cotação ativa para 'XPTO123' (sem resultados)"
        bot = self.bot(self.failing({"profile": AgentResult("profile_agent", "failed", error=err)}))
        self.run_all(bot, msg("/analisar XPTO123"))
        self.assertIn("Não encontrei «XPTO123»", self.api.edits[-1]["text"])
        self.assertNotIn("ValueError", self.api.all_text())

    def test_usage_limit_waits_and_resumes_the_same_run(self):
        """B11 — o erro chegava cru ("sem dados de entrada ['decision']") e a análise perdia-se."""
        limit = "ResultError: Claude Code returned an error result: You've hit your 5-hour limit · resets 8am (Europe/Lisbon)"
        prof = AgentResult("profile_agent", "ok", {"symbol": "AAPL", "name": "Apple Inc."})
        results = {"profile": prof, "rating": AgentResult("rating_agent", "failed", error=limit),
                   "guard": AgentResult("guard_agent", "skipped", error="sem dados de entrada ['decision'] (nó a montante falhou)")}
        bot = self.bot(self.failing(results))
        self.run_all(bot, msg("/analisar AAPL"))
        final = self.api.edits[-1]
        self.assertIn("limite de utilização do Claude", final["text"])
        self.assertIn("08:00", final["text"])
        self.assertNotIn("decision", final["text"])
        self.assertEqual(self.api.labels(final), ["🔁 Tentar já", "✖️ Desistir"])
        job = jobs.active(self.conn)[0]
        self.assertEqual(job["state"], "waiting")
        first_run = job["run_id"]
        self.run_all(bot, tap(f"q|{job['id']}"))                                   # "Tentar já"
        self.assertEqual(self.flows[1][2]["run_id"], first_run)                    # mesma execução…
        self.assertTrue(self.flows[1][2]["resume"])                                # …a reaproveitar os nós feitos

    def test_other_failures_get_a_human_message_and_a_retry_button(self):
        prof = AgentResult("profile_agent", "ok", {"symbol": "AAPL", "name": "Apple Inc."})
        for err, expect in (("timeout (180s)", "excesso de tempo"),
                            ("ResultError: Invalid API key · Please run /login", "sessão do Claude expirou"),
                            ("ResultError: Credit balance is too low", "créditos da API")):
            self.api.__init__()
            bot = self.bot(self.failing({"profile": prof, "rating": AgentResult("rating_agent", "failed", error=err),
                                         "guard": AgentResult("guard_agent", "skipped", error="sem dados de entrada ['decision']")}))
            self.run_all(bot, msg("/analisar AAPL", uid=int(time.time() * 1000) % 100000))
            final = self.api.edits[-1]
            self.assertIn(expect, final["text"], err)
            self.assertEqual(self.api.labels(final), ["🔁 Repetir"])
            self.assertNotIn("ResultError", final["text"])

    def test_internal_error_is_reported_and_the_bot_survives(self):
        async def boom(flow, params, **kw):
            raise RuntimeError(r"c:\Users\x\segredo")
        bot = self.bot(boom)
        self.run_all(bot, msg("/analisar AAPL"), msg("/ajuda", uid=2))
        self.assertIn("erro interno", self.api.edits[-1]["text"])
        self.assertNotIn("segredo", self.api.all_text())                           # sem caminhos locais nem traces
        self.assertEqual(jobs.recent(self.conn, 1)[0]["state"], "failed")
        self.assertIn("Agentock", self.api.sent[-1]["text"])                       # continuou a responder

    def test_card_failure_still_delivers_the_verdict(self):
        bot = self.bot()
        self.api.send_photo = lambda *a, **k: (_ for _ in ()).throw(telegram.TelegramError(400, "Bad Request"))
        self.run_all(bot, msg("/analisar AAPL"))
        self.assertIn("Apple — COMPRA", self.api.edits[-1]["text"])
        self.assertIn("🧾 Porquê", self.api.labels(self.api.sent[-1]))
        self.assertEqual(jobs.recent(self.conn, 1)[0]["state"], "done")

    def test_deleted_status_message_falls_back_to_a_new_one(self):
        bot = self.bot()
        self.api.fail_edit = True
        self.run_all(bot, msg("/analisar AAPL"))
        self.assertIn("Apple — COMPRA", self.api.sent[-1]["text"])


class CancelAndResumeTests(BotCase):
    def test_cancel_stops_the_running_analysis(self):
        async def slow(flow, params, **kw):
            await asyncio.wait_for(kw["cancel"].wait(), 5)
            return RunReport(kw["run_id"], [], {}, cancelled=True)

        async def go():
            bot = self.bot(slow)
            await bot.on_update(msg("/analisar AAPL"))
            task = asyncio.create_task(bot.run_job(jobs.claim(self.conn)))
            await asyncio.sleep(0.05)
            await bot.on_update(msg("/cancelar", uid=2))
            await asyncio.wait_for(task, 3)
        asyncio.run(go())
        self.assertEqual(jobs.recent(self.conn, 1)[0]["state"], "cancelled")
        self.assertIn("cancelada", self.api.edits[-1]["text"])

    def test_cancel_removes_queued_jobs(self):
        bot = self.bot()
        self.run_all(bot, msg("/analisar AAPL"), msg("/analisar MSFT", uid=2), work=False)
        ids = [j["id"] for j in jobs.active(self.conn)]
        self.run_all(bot, tap(f"x|{ids[1]}"), work=False)
        self.assertEqual([j["id"] for j in jobs.active(self.conn)], ids[:1])

    def test_restart_resumes_interrupted_job_with_the_same_run(self):
        """O processo morreu a meio: a tarefa não se perde e reaproveita o que já estava feito."""
        bot = self.bot()
        asyncio.run(bot.startup())                                                # 1.º arranque: avisa que está ligado
        self.assertIn("Agentock ligado", self.api.sent[0]["text"])
        self.assertNotIn("Parado desde", self.api.sent[0]["text"])
        self.run_all(bot, msg("/analisar AAPL"), work=False)
        job = jobs.claim(self.conn)                                               # começou a correr…
        jobs.update(self.conn, job["id"], run_id="20261115T000000-AAPL-abc123")
        jobs.kv_set(self.conn, "last_heartbeat", "2026-11-15T03:00:00+00:00")     # …e o processo morreu aqui
        self.api.__init__()
        bot2 = self.bot()
        asyncio.run(bot2.startup())
        self.assertIn("Agentock ligado", self.api.sent[0]["text"])
        self.assertIn("terminou de forma inesperada", self.api.sent[0]["text"])
        self.assertIn("A retomar: AAPL", self.api.sent[0]["text"])
        self.assertIn("setMyCommands", [c[0] for c in self.api.calls])
        self.run_all(bot2)
        self.assertEqual(self.flows[0][2]["run_id"], "20261115T000000-AAPL-abc123")
        self.assertTrue(self.flows[0][2]["resume"])

    def test_job_interrupted_twice_fails_instead_of_looping(self):
        job, _ = jobs.enqueue(self.conn, "ticker", {"query": "AAPL"})
        jobs.claim(self.conn)
        jobs.recover(self.conn)
        jobs.claim(self.conn)
        out = jobs.recover(self.conn)
        self.assertEqual([j["id"] for j in out["failed"]], [job["id"]])
        self.assertEqual(jobs.get(self.conn, job["id"])["state"], "failed")


class CommandsTests(BotCase):
    def analysed(self, bot):
        self.run_all(bot, msg("/analisar AAPL"))
        self.api.__init__()

    def test_watchlist_summary_and_buttons(self):
        bot = self.bot()
        self.analysed(bot)
        self.run_all(bot, msg("/seguir AAPL", uid=2), msg("/seguir MSFT", uid=3), msg("/hoje", uid=4))
        summary = self.api.sent[-1]
        self.assertIn("<b>AAPL</b> — Compra 60%", summary["text"])
        self.assertIn("<b>MSFT</b> — ainda sem análise", summary["text"])
        self.assertIn("▶️ Analisar todas", self.api.labels(summary))
        self.run_all(bot, tap("w|run"), work=False)
        confirm = self.api.sent[-1]
        self.assertIn("Analisar as 2 ações", confirm["text"])
        self.run_all(bot, tap(self.api.callbacks(confirm)[0], uid=60), work=False)
        self.assertEqual(sorted(j["args"]["query"] for j in jobs.active(self.conn)), ["AAPL", "MSFT"])
        self.assertTrue(all(j["args"]["compact"] for j in jobs.active(self.conn)))
        self.run_all(bot, msg("/deixar MSFT", uid=5), work=False)
        self.assertEqual([w["ticker"] for w in jobs.watchlist(self.conn)], ["AAPL"])

    def test_history_compare_and_detail_cost_nothing(self):
        bot = self.bot()
        self.analysed(bot)
        self.run_all(bot, msg("/historico aapl", uid=2), msg("/comparar AAPL MSFT", uid=3), msg("/detalhe_AAPL", uid=4))
        self.assertEqual(len(self.flows), 1)                                      # só a análise inicial
        text = self.api.all_text()
        self.assertIn("Histórico</b> · AAPL", text)
        self.assertRegex(text, r"🟢 \d+ \w+, \d\d:\d\d · Compra · 60% · 356,40 USD")
        self.assertIn("Ainda não analisei: MSFT", text)
        self.assertEqual(len(self.api.photos), 1)

    def test_universe_needs_confirmation_with_cost(self):
        bot = self.bot()
        self.run_all(bot, msg("/universo 3"))
        text = self.api.sent[-1]["text"]
        if "Ainda não tenho a lista" not in text:                                 # depende de data/universe.json
            self.assertIn("USD", text)
            self.assertEqual(self.api.labels(self.api.sent[-1]), ["✅ Confirmar", "Cancelar"])
        self.assertEqual(self.flows, [])

    def test_settings_and_alerts_are_buttons(self):
        bot = self.bot()
        self.run_all(bot, msg("/definicoes"), tap("f|ver|v1"), msg("/alertas", uid=3), tap("f|auto|fecho", uid=51),
                     tap("f|sum|on", uid=52), msg("/analisar AAPL", uid=4))
        self.assertEqual(jobs.setting(self.conn, "rating_version"), "v1")
        self.assertEqual(jobs.setting(self.conn, "auto_analysis"), "fecho")
        self.assertEqual(self.flows[0][1]["rating_version"], "v1")
        self.assertEqual(self.flows[0][1]["debate"], False)
        self.assertIn("Só recebes alerta quando uma classificação muda", self.api.all_text())

    def test_status_shows_queue_usage_and_last_jobs(self):
        bot = self.bot()
        self.analysed(bot)
        self.run_all(bot, msg("/analisar MSFT", uid=2), msg("/estado", uid=3), work=False)
        text = self.api.sent[-1]["text"]
        self.assertIn("Agentock ligado", text)
        self.assertIn("MSFT — em fila", text)
        self.assertIn("✅", text)
        self.assertIn("Autenticação:", text)

    def test_section_buttons_edit_a_single_detail_message(self):
        bot = self.bot()
        self.run_all(bot, msg("/analisar AAPL"))
        row = self.conn.execute("SELECT id FROM runs").fetchone()["id"]
        self.api.__init__()
        self.run_all(bot, tap(f"s|{row}|rz", message_id=900), tap(f"s|{row}|rk", uid=51, message_id=900))
        self.assertEqual(len(self.api.sent), 1)                                   # 1.º toque: nova mensagem de detalhe
        self.assertEqual(self.api.edits[-1]["id"], self.api.sent[0]["id"])        # 2.º toque: edita essa mesma
        self.run_all(bot, tap("s|999|zz", uid=52), tap("zz", uid=53), tap("", uid=54))   # botões antigos/adulterados
        self.assertNotIn("Error", self.api.all_text())
        self.assertIn("já não está disponível", self.api.all_text())

    def test_unknown_command_shows_help(self):
        bot = self.bot()
        self.run_all(bot, msg("/xpto"))
        self.assertIn("/analisar AAPL", self.api.sent[0]["text"])

    def test_menu_commands_are_valid_for_telegram(self):
        for name, desc in tb.MENU:
            self.assertRegex(name, r"^[a-z0-9_]{1,32}$")
            self.assertLessEqual(len(desc), 256)


class SchedulerTests(BotCase):
    def test_daily_summary_once_a_day_at_the_configured_hour(self):
        bot = self.bot()
        jobs.watch_add(self.conn, "AAPL")
        jobs.set_setting(self.conn, "daily_summary", "on")
        early = datetime(2026, 11, 16, 7, 0, tzinfo=timezone.utc)                 # 07:00 em Lisboa
        asyncio.run(bot.tick(early))
        self.assertEqual(self.api.sent, [])
        asyncio.run(bot.tick(early + timedelta(hours=2)))
        asyncio.run(bot.tick(early + timedelta(hours=3)))
        self.assertEqual(len(self.api.sent), 1)
        self.assertEqual(jobs.kv_get(self.conn, "last_heartbeat")[:13], "2026-11-16T10")

    def test_auto_analysis_after_the_close_fires_once_per_session(self):
        bot = self.bot()
        jobs.watch_add(self.conn, "AAPL")
        jobs.watch_add(self.conn, "005930.KS")
        after_ny_close = datetime(2026, 11, 13, 21, 30, tzinfo=timezone.utc)      # NYSE fechou às 21:00 UTC
        self.assertEqual(bot.due_auto(after_ny_close, "fecho"), ["AAPL"])         # Seul fechou há 15 h: não dispara
        self.assertEqual(bot.due_auto(after_ny_close + timedelta(minutes=5), "fecho"), [])   # já disparou nesta sessão
        before_seoul_open = datetime(2026, 11, 15, 23, 40, tzinfo=timezone.utc)   # Seul abre às 00:00 UTC de dia 16
        self.assertEqual(bot.due_auto(before_seoul_open, "abertura"), ["005930.KS"])

    def test_auto_analysis_is_off_by_default(self):
        self.assertEqual(jobs.setting(self.conn if jobs.init(self.conn) is None else self.conn, "auto_analysis"), "off")
        self.assertEqual(jobs.setting(self.conn, "daily_summary"), "off")


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        from tools import bot_watchdog
        self.wd = bot_watchdog
        self.conn = db.connect(":memory:")
        self.now = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
        self.killed = []

    def check(self, alive):
        return self.wd.check(self.conn, self.now, is_alive=lambda pid: alive, do_kill=self.killed.append)

    def test_never_started_or_recent_heartbeat_is_ok(self):
        self.assertEqual(self.check(False)["action"], "ok")
        jobs.kv_set(self.conn, "last_heartbeat", (self.now - timedelta(minutes=2)).isoformat())
        self.assertEqual(self.check(True)["action"], "ok")
        self.assertEqual(self.killed, [])

    def test_hung_process_is_killed_and_reported_once(self):
        jobs.kv_set(self.conn, "last_heartbeat", (self.now - timedelta(minutes=20)).isoformat())
        jobs.kv_set(self.conn, "pid", 4321)
        first = self.check(True)
        self.assertEqual((first["action"], first["notify"], self.killed), ("killed", True, [4321]))
        self.assertFalse(self.check(True)["notify"])                # mesmo incidente: não repete o aviso

    def test_stopped_bot_without_supervisor_is_reported(self):
        jobs.kv_set(self.conn, "last_heartbeat", (self.now - timedelta(hours=3)).isoformat())
        out = self.check(False)
        self.assertEqual((out["action"], out["notify"], self.killed), ("down", True, []))


class ProgressTests(unittest.TestCase):
    def test_text_and_eta(self):
        clock = [0.0]
        order = ["profile", "news_scan", "rating"]
        deps = {"profile": set(), "news_scan": {"profile"}, "rating": {"news_scan"}}
        p = Progress("Apple (AAPL)", order, deps, expected={"profile": 3, "news_scan": 20, "rating": 20}, clock=lambda: clock[0])
        self.assertAlmostEqual(p.eta(), 43)
        p.on_event({"type": "start", "node": "profile"})
        p.on_event({"type": "done", "node": "profile", "status": "ok"})
        p.on_event({"type": "start", "node": "news_scan"})
        clock[0] = 10.0
        self.assertAlmostEqual(p.eta(), 30)                                       # 10 s que faltam às notícias + 20
        text = p.text(queued_behind=2)
        self.assertIn("A analisar Apple (AAPL)", text)
        self.assertIn("✅ Empresa e cotação", text)
        self.assertIn("▶️ Notícias e sentimento", text)
        self.assertIn("⬜ Debate e classificação", text)
        self.assertIn("faltam ~30 s", text)
        self.assertIn("/cancelar", text)
        self.assertIn("2 em fila", text)
        self.assertLess(len(text), 500)


class ErrorTextTests(unittest.TestCase):
    def test_classify(self):
        cases = {"You've hit your 5-hour limit · resets 8am (Europe/Lisbon)": "limit",
                 "Invalid API key · Please run /login": "auth", "Credit balance is too low": "credit",
                 "timeout (240s)": "timeout", "DataUnavailable: financials SSU: nenhum fornecedor respondeu": "no_data",
                 "sem dados de entrada ['decision'] (nó a montante falhou)": "skipped",
                 "ValueError: 'ABC' é ambíguo — escolhe uma": "ambiguous", "KeyError: 'x'": "other"}
        for err, kind in cases.items():
            self.assertEqual(errors.classify(err), kind, err)

    def test_reset_time_is_the_next_occurrence_in_lisbon(self):
        now = datetime(2026, 11, 15, 3, 40, tzinfo=timezone.utc)
        self.assertEqual(errors.reset_time("resets 8am (Europe/Lisbon)", now), datetime(2026, 11, 15, 8, 0, tzinfo=timezone.utc))
        self.assertEqual(errors.reset_time("resets 3am (Europe/Lisbon)", now), datetime(2026, 11, 16, 3, 0, tzinfo=timezone.utc))
        self.assertEqual(errors.reset_time("resets 11:30pm", now).hour, 23)
        self.assertIsNone(errors.reset_time("sem hora"))

    def test_root_cause_skips_consequences(self):
        problems = {"guard": AgentResult("g", "skipped", error="sem dados de entrada ['decision']"),
                    "rating": AgentResult("r", "failed", error="timeout (180s)")}
        self.assertEqual(errors.root_cause(problems)[::2], ("rating", "timeout"))

    def test_messages_never_leak_technical_text(self):
        for kind in ("limit", "auth", "credit", "timeout", "no_data", "network", "cancelled", "other"):
            text = errors.humanize(kind, subject="Apple", error="Traceback HTTPSConnectionPool(host=...)", node="rating")
            self.assertNotRegex(text, r"Traceback|HTTPSConnection|Error\b")
            self.assertLess(len(text), 260)


class TelegramClientTests(unittest.TestCase):
    """B10 — 429, falhas de rede e HTML inválido não podem fazer perder uma mensagem."""

    def api(self, responses):
        api = telegram.TelegramAPI("TOKEN123", "42", sleep=lambda s: self.slept.append(s))
        self.slept, self.requests = [], []

        def fake_open(req, timeout):
            self.requests.append(req)
            r = responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        api._open = fake_open
        return api

    def http_error(self, code, body):
        return urllib.error.HTTPError("https://api.telegram.org/botTOKEN123/x", code, "err", {}, io.BytesIO(json.dumps(body).encode()))

    def test_429_waits_retry_after_and_succeeds(self):
        api = self.api([self.http_error(429, {"description": "Too Many Requests", "parameters": {"retry_after": 3}}),
                        {"ok": True, "result": {"message_id": 5}}])
        self.assertEqual(api.send_message("olá"), {"message_id": 5})
        self.assertEqual(self.slept, [3.0])

    def test_network_error_is_retried_and_never_shows_the_token(self):
        api = self.api([urllib.error.URLError("down")] * 3)
        with self.assertRaises(telegram.TelegramError) as e:
            api.send_message("olá")
        self.assertNotIn("TOKEN123", str(e.exception))
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(api.redact("https://api.telegram.org/botTOKEN123/x"), "https://api.telegram.org/bot<token>/x")

    def test_bad_html_is_resent_as_plain_text(self):
        api = self.api([self.http_error(400, {"description": "Bad Request: can't parse entities"}),
                        {"ok": True, "result": {"message_id": 6}}])
        self.assertEqual(api.send_message("<b>olá", html=True), {"message_id": 6})
        self.assertIn(b"text=ol%C3%A1", self.requests[1].data)
        self.assertNotIn(b"parse_mode", self.requests[1].data)

    def test_edit_of_a_gone_message_returns_false(self):
        api = self.api([self.http_error(400, {"description": "Bad Request: message to edit not found"})])
        self.assertFalse(api.edit_message(1, "x"))
        api = self.api([self.http_error(400, {"description": "Bad Request: message is not modified"})])
        self.assertTrue(api.edit_message(1, "x"))

    def test_old_callback_is_ignored(self):
        api = self.api([self.http_error(400, {"description": "Bad Request: query is too old"})])
        api.answer_callback("cb")                                                  # não levanta

    def test_chunks_respect_limits_lines_and_pre_blocks(self):
        text = "\n".join(f"linha {i} " + "x" * 60 for i in range(200))
        parts = telegram.chunks(text)
        self.assertTrue(all(len(p) <= telegram.CHUNK + 6 for p in parts))
        self.assertEqual("\n".join(parts), text)
        pre = "<pre>" + "\n".join("a" * 50 for _ in range(120)) + "</pre>\nfim"
        parts = telegram.chunks(pre)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(p.count("<pre>") == p.count("</pre>") for p in parts))   # nenhum bloco fica aberto
        self.assertTrue(all(len(p) <= telegram.MAX_TEXT for p in telegram.chunks("y" * 9000)))   # linha gigante

    def test_caption_is_cut_on_a_line_with_tags_closed(self):
        cap = "<b>Título</b>\n<i>" + "palavra " * 200 + "</i>\nfim"
        out = telegram.fit_caption(cap)
        self.assertLessEqual(len(out), telegram.MAX_CAPTION)
        self.assertEqual(out.count("<i>"), out.count("</i>"))
        self.assertEqual(telegram.fit_caption("curta"), "curta")

    def test_keyboard_rejects_long_callback_data(self):
        with self.assertRaises(ValueError):
            telegram.keyboard([[("x", "y" * 65)]])


class VerdictTests(unittest.TestCase):
    DATA = {"run": {"id": 7, "ticker": "005930.KS", "rating": 1, "confidence": 0.55, "price": 206000.0, "currency": "KRW",
                    "ts": "2026-11-14T17:09:30+00:00", "version": "v2"},
            "payload": {"headline": "Lucros fortes e preço baixo face aos lucros, mas a memória é cíclica e o gráfico está fraco"},
            "reasons": ["Fundamentais e valorização: P/E forward 2,66 e EV/EBITDA 3,56."],
            "outputs": {"profile": {"name": "Samsung Electronics Co., Ltd.", "change_pct": -0.96},
                        "forecast": {"expected_return_12m_pct": 11.89, "scenarios": [{"price_12m": 105000}, {"price_12m": 215000},
                                                                                     {"price_12m": 340000}]},
                        "calendar": {"next_earnings": "2027-01-27", "days_to_earnings": 74}}}

    def test_verdict_fits_the_five_second_budget(self):
        text = M.verdict(self.DATA, previous={"rating": 0, "confidence": 0.4, "ts": "2026-11-14T12:47:23+00:00"},
                         gaps=2, total=31)
        self.assertTrue(text.startswith("🟢 <b>Samsung Electronics — COMPRA</b> · confiança 55%"))
        self.assertIn("206.000 KRW (−0,96% hoje) · 005930.KS", text)
        self.assertIn("Antes: MANTER 40%", text)
        self.assertIn("12 meses: +11,9% esperado (−49% a +65%)", text)
        self.assertIn("Resultados a 27 jan 2027", text)
        self.assertIn("2 de 31 passos sem dados", text)
        self.assertLessEqual(len(telegram.strip_html(text)), 350)

    def test_confirmed_change_is_announced(self):
        text = M.verdict(self.DATA, change={"changed": True, "kind": "confirmed", "old": "Manter", "new": "Compra"})
        self.assertIn("Mudou: MANTER → COMPRA (confirmada)", text)

    def test_fallback_point_is_not_just_the_dimension_name(self):
        """B14 — a legenda da AAPL dizia só "• Fundamentais • Analistas e alvos • Técnica e momentum"."""
        self.assertEqual(M.point_of("Fundamentais e valorização: P/E forward 2,66 e EV/EBITDA 3,56. Mais texto."),
                         "P/E forward 2,66 e EV/EBITDA 3,56")
        data = {**self.DATA, "payload": {}}
        self.assertIn("P/E forward 2,66", M.verdict(data))

    def test_formats(self):
        self.assertEqual((M.num_pt(1234.56), M.price_pt(206000.0), M.price_pt(0.093), M.price_pt(999.999)),
                         ("1.234,56", "206.000", "0,093", "1.000"))
        self.assertEqual((M.pct_pt(-0.004, 0), M.pct_pt(11.89), M.pct_pt(-49.0, 0)), ("0%", "+11,9%", "−49%"))
        self.assertEqual(M.when_pt("2026-07-01T12:00:00+00:00"), "1 jul, 13:00")   # hora de verão de Lisboa
        self.assertEqual(M.when_pt("2026-11-14T17:09:30+00:00"), "14 nov, 17:09")


if __name__ == "__main__":
    unittest.main()
