"""Bot Telegram do Agentock — a interface do dia a dia: tudo se faz daqui, sem terminal.

  python tools/telegram_bot.py        (fica a correr; ver tools/run_bot.cmd e tools/install_bot_task.ps1)

Só responde ao dono (TELEGRAM_CHAT_ID). Comandos:
  /analisar AAPL [v1|v2]   análise completa → veredicto em texto + cartão com botões   (também: escrever só "AAPL")
  /hoje · /lista · /seguir X · /deixar X      a tua lista de ações e o resumo do dia
  /comparar A B · /historico X · /detalhe X   sobre análises já feitas (não gastam nada)
  /ipos · /ipo X · /universo N                IPOs e as N maiores empresas (com custo e confirmação)
  /alertas · /definicoes · /estado · /cancelar · /ajuda

Como funciona (Fase 10):
- cada pedido de análise é uma tarefa gravada em SQLite (core/jobs.py) antes de se responder: sobrevive a reinícios,
  não se duplica, e uma de cada vez é corrida pelo worker;
- o progresso é uma única mensagem que se vai editando; /cancelar pára a análise em curso;
- os erros chegam em linguagem humana com o próximo passo (core/errors.py); o detalhe técnico fica em bot.log;
- limite de utilização do Claude atingido → a tarefa fica à espera e é retomada sozinha à hora de reposição;
- comandos escritos enquanto o bot esteve desligado não são executados às cegas: pergunta se ainda os queres.
"""
import asyncio
import json
import logging
import os
import re
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import core.env  # noqa: E402,F401
from core import db, errors, jobs, messages as M, report_data, sections  # noqa: E402
from core.orchestrator import deps, layers, load_flow, run_flow  # noqa: E402
from core.progress import Progress  # noqa: E402
from core.ratings import IpoRating, Rating  # noqa: E402
from core.runner import new_run_id  # noqa: E402
from core.schemas import IpoSynthesis  # noqa: E402
from core.telegram import TelegramAPI, TelegramError, keyboard  # noqa: E402

log = logging.getLogger("agentock.bot")
STALE_SECONDS = 120          # comandos mais velhos do que isto (bot desligado) pedem confirmação
EDIT_EVERY = 2.5             # segundos mínimos entre edições da mensagem de progresso (limites do Telegram)
QUERY_RE = re.compile(r"^[\w .&'^=\-]{1,40}$")
UNDERSCORE_CMDS = ("analisar", "run", "detalhe", "ipo", "seguir", "deixar", "historico", "history", "status")
MENU = [("analisar", "Analisar uma ação: /analisar AAPL"), ("hoje", "Resumo do dia da tua lista"),
        ("lista", "Ações que segues"), ("comparar", "Comparar duas: /comparar AAPL MSFT"),
        ("historico", "Classificações anteriores: /historico AAPL"), ("ipos", "IPOs dos próximos 30 dias"),
        ("universo", "Analisar as N maiores (mostra o custo antes)"), ("alertas", "Análises automáticas e resumo diário"),
        ("definicoes", "Versão da classificação"), ("estado", "Sistema, fila e utilização"),
        ("cancelar", "Parar a análise em curso"), ("ajuda", "Como usar")]
HELP = ("<b>Agentock</b> — análise de ações\n\n"
        "Escreve um ticker ou um nome (<code>AAPL</code>, <code>Samsung</code>, <code>005930.KS</code>) e eu analiso.\n\n"
        "/analisar AAPL — análise completa (~2 min)\n"
        "/hoje — resumo da tua lista\n"
        "/lista · /seguir AAPL · /deixar AAPL\n"
        "/comparar AAPL MSFT — lado a lado\n"
        "/historico AAPL — classificações anteriores\n"
        "/ipos — IPOs dos próximos 30 dias\n"
        "/universo 10 — as 10 maiores do mundo (mostra o custo antes)\n"
        "/alertas — análises automáticas e resumo diário\n"
        "/definicoes · /estado · /cancelar\n\n"
        f"<i>{M.DISCLAIMER_SHORT}</i>")


def rating_params(version: str) -> dict:
    return {"rating_agent": "rating_agent" if version == "v2" else "rating_v1_agent", "rating_version": version,
            "debate": version == "v2"}


def symbol_from_command(arg: str) -> str:
    """'005930_KS' → '005930.KS' (o último '_' antes de um sufixo de bolsa volta a ser '.')."""
    m = re.fullmatch(r"(.+)_([A-Z]{1,3})", arg.upper())
    return f"{m.group(1)}.{m.group(2)}" if m else arg.upper()


def run_command(symbol: str) -> str:
    return f"/analisar_{M.command_arg(symbol)}"


def resolve_ticker(conn, arg: str) -> str | None:
    """'005930_KS', '005930.KS' ou 'aapl' → ticker gravado no histórico."""
    a = arg.strip().upper()
    for (t,) in conn.execute("SELECT DISTINCT ticker FROM runs").fetchall():
        if t.upper() == a or M.command_arg(t).upper() == a:
            return t
    return None


def profile_error_text(query: str, error: str) -> tuple[str, list[str]]:
    """Erro do perfil (ambíguo / sem cotação ativa) em linguagem de gente + símbolos alternativos para botões."""
    msg = re.sub(r"^ValueError:\s*", "", error or "")
    options = list(dict.fromkeys(re.findall(r"→ ([A-Z0-9.\-^=]+)", msg)))
    kind = errors.classify(msg)
    if kind == "ambiguous":
        names = re.findall(r"([^;:]+?) → ([A-Z0-9.\-^=]+)", msg.split("escolhe uma:")[-1])
        lines = [f"🤔 <b>«{M.esc(query)}» pode ser {len(options)} empresas.</b> Qual queres?"]
        lines += [f"• {M.esc(M.shorten(n.strip(), 40))} — <code>{M.esc(s)}</code>" for n, s in names[:5]]
        return "\n".join(lines), options
    if kind == "not_found":
        detail = re.search(r"\((.+)\)\s*$", msg)
        why = f"\n<i>{M.esc(M.shorten(detail.group(1), 200))}</i>" if detail and "sem resultados" not in detail.group(1) else ""
        return (f"🔎 <b>Não encontrei «{M.esc(query)}».</b> Nenhuma bolsa tem uma ação ativa com esse código ou nome.{why}\n"
                "Tenta o código (AAPL), o código com bolsa (005930.KS) ou o nome (Samsung)."), options
    return M.esc(errors.humanize(kind if kind != "other" else "no_data", subject=query, error=msg, node="profile")), options


def ipo_detail_text(conn, arg: str) -> str:
    a = arg.strip()
    rows = conn.execute("SELECT * FROM ipo_ratings ORDER BY id DESC").fetchall()
    row = next((r for r in rows if a.isdigit() and r["id"] == int(a)), None) or \
        next((r for r in rows if r["symbol"] and M.command_arg(r["symbol"]).upper() == a.upper()), None) or \
        next((r for r in rows if a and a.lower() in (r["name"] or "").lower()), None)
    if not row:
        return f"Sem análise de IPO para «{M.esc(a)}». Vê /ipos."
    s = IpoSynthesis.model_validate(json.loads(row["payload"]))
    head = M.ipo_rating(s, IpoRating(row["rating"]), None, None).split("\n")[:3]  # cabeçalho igual ao alerta
    sec = lambda title, items, n=4: (["", f"<b>{title}</b>"] + [f"• {M.esc(M.shorten(x, 220))}" for x in items[:n]]) if items else []  # noqa: E731
    lines = head + ([f"<i>{M.esc(s.headline)}</i>"] if s.headline else [])
    lines += ["", "<b>Valorização</b>", M.esc(M.shorten(s.valuation_view, 450)),
              "", "<b>Financeiras</b>", M.esc(M.shorten(s.financials, 400))]
    lines += sec("A favor", s.bull_case, 3) + sec("Contra", s.bear_case, 3) + sec("A acompanhar", s.watch_points, 3)
    if s.not_disclosed:
        lines += ["", "<i>" + M.esc("Por divulgar: " + ", ".join(M.first_clause(x) for x in s.not_disclosed[:6])) + "</i>"]
    return "\n".join(lines + ["", f"<i>{M.DISCLAIMER_SHORT}</i>"])


class Bot:
    def __init__(self, api: TelegramAPI, conn=None, *, runner=run_flow, allowed_users: set[str] | None = None,
                 clock=time.time):
        self.api, self.runner, self.clock = api, runner, clock
        self.conn = conn or db.connect()
        jobs.init(self.conn)
        self.chat_id = str(api.chat_id)
        self.allowed_users = {str(u) for u in (allowed_users or set())}
        self.cancel: asyncio.Event | None = None
        self.current: dict | None = None
        self.progress: Progress | None = None
        self.wake = asyncio.Event()
        self.started = clock()
        self._stale: list[str] = []
        self._last_edit, self._last_text, self._edit_task, self._edit_pending = 0.0, "", None, False

    # ------------------------------------------------------------------ Telegram
    async def tg(self, fn, *a, **k):
        return await asyncio.to_thread(fn, *a, **k)

    async def say(self, text: str, buttons: dict | None = None, html: bool = True) -> int | None:
        try:
            msg = await self.tg(self.api.send_message, text, html, buttons)
            return (msg or {}).get("message_id")
        except TelegramError as e:
            log.error("não consegui enviar a mensagem: %s", self.api.redact(e))
            return None

    async def edit(self, message_id: int | None, text: str, buttons: dict | None = None, html: bool = True) -> int | None:
        """Edita a mensagem; se já não der (apagada, antiga), envia uma nova. Devolve o id da que ficou."""
        if message_id and await self.tg(self.api.edit_message, message_id, text, html, buttons):
            return message_id
        return await self.say(text, buttons, html)

    def allowed(self, chat: dict | None, sender: dict | None) -> bool:
        """Só o chat configurado; num grupo, só os utilizadores autorizados (TELEGRAM_ALLOWED_USER_IDS)."""
        chat, sender = chat or {}, sender or {}
        if str(chat.get("id")) != self.chat_id:
            return False
        if chat.get("type", "private") == "private":
            return sender.get("id") is None or str(sender.get("id")) == self.chat_id or str(sender["id"]) in self.allowed_users
        return str(sender.get("id")) in self.allowed_users

    # ------------------------------------------------------------------ updates
    async def on_update(self, u: dict) -> None:
        uid = u.get("update_id")
        try:
            if "callback_query" in u:
                cq = u["callback_query"]
                if self.allowed((cq.get("message") or {}).get("chat"), cq.get("from")):
                    await self.on_callback(cq)
            else:
                msg = u.get("message") or u.get("edited_message") or {}
                text = (msg.get("text") or "").strip()
                if text and self.allowed(msg.get("chat"), msg.get("from")):
                    if msg.get("date") and self.clock() - msg["date"] > STALE_SECONDS:
                        self._stale.append(text)      # escrito com o bot desligado: não se executa às cegas
                    else:
                        log.info("comando: %s", text[:120])
                        await self.on_text(text, uid)
        except Exception:  # noqa: BLE001 — um erro num pedido nunca pode parar o bot nem perder-se em silêncio
            log.exception("erro ao tratar o update %s", uid)
            await self.say("⚠️ Não consegui tratar esse pedido. O erro ficou registado; vê /estado.", html=False)
        finally:
            if uid is not None:
                jobs.kv_set(self.conn, "tg_offset", uid + 1)

    async def flush_stale(self) -> None:
        if not self._stale:
            return
        items, self._stale = self._stale[-5:], []
        rows = []
        for t in items:
            if t.startswith("/") and self.parse(t)[0] in ("analisar", "run"):
                token = self.remember({"kind": "text", "text": t})
                rows.append([(f"🔁 {M.shorten(t, 28)}", f"y|{token}")])
        lines = ["💤 <b>Estive desligado</b> e não executei:"] + [f"• <code>{M.esc(M.shorten(t, 60))}</code>" for t in items]
        if rows:
            lines.append("Toca para repetir o que ainda quiseres.")
        await self.say("\n".join(lines), keyboard(rows) if rows else None)

    def remember(self, payload: dict) -> str:
        """Guarda uma ação pendente de confirmação; o botão leva só um token (callback_data ≤ 64 bytes)."""
        token = secrets.token_hex(5)
        jobs.kv_set(self.conn, f"confirm:{token}", {**payload, "ts": self.clock()})
        return token

    @staticmethod
    def parse(text: str) -> tuple[str, list[str]]:
        parts = text.strip().split()
        cmd = parts[0].split("@")[0].lstrip("/").lower()
        args = parts[1:]
        head, _, tail = cmd.partition("_")
        if tail and head in UNDERSCORE_CMDS:          # forma tocável: /analisar_005930_KS
            cmd, args = head, [symbol_from_command(tail)] + args
        return cmd, args

    async def on_text(self, text: str, update_id: int | None = None) -> None:
        if not text.startswith("/"):
            return await self.free_text(text)
        cmd, args = self.parse(text)
        handler = {
            "analisar": self.cmd_analisar, "run": self.cmd_analisar, "a": self.cmd_analisar,
            "detalhe": self.cmd_detalhe, "historico": self.cmd_historico, "history": self.cmd_historico,
            "status": self.cmd_historico, "lista": self.cmd_lista, "seguir": self.cmd_seguir, "deixar": self.cmd_deixar,
            "hoje": self.cmd_hoje, "comparar": self.cmd_comparar, "ipos": self.cmd_ipos, "ipo": self.cmd_ipo,
            "universo": self.cmd_universo, "alertas": self.cmd_alertas, "definicoes": self.cmd_definicoes,
            "estado": self.cmd_estado, "cancelar": self.cmd_cancelar,
        }.get(cmd)
        if handler is None:
            return await self.say(HELP)
        await handler(args, update_id)

    async def free_text(self, text: str) -> None:
        """Texto sem '/': quase sempre é um ticker ou um nome. Pergunta antes de gastar uma análise."""
        q = re.sub(r"\s+", " ", text).strip()
        if not QUERY_RE.match(q):
            return await self.say("Escreve um ticker ou o nome de uma empresa (ex.: <code>AAPL</code>, "
                                  "<code>Samsung</code>), ou vê /ajuda.")
        token = self.remember({"kind": "ticker", "query": q})
        est = self.estimate()
        await self.say(f"Analisar <b>{M.esc(q)}</b>? Demora ~{M.duration_pt(est['seconds'])} e gasta cerca de "
                       f"{M.num_pt(est['usd'], 2)} USD equivalentes da subscrição.",
                       keyboard([[("✅ Sim", f"y|{token}"), ("Não", "n")]]))

    # ------------------------------------------------------------------ medições para as estimativas
    def estimate(self) -> dict:
        """Custo e tempo médios das últimas análises completas (para mostrar antes de gastar)."""
        rows = self.conn.execute(
            "SELECT SUM(COALESCE(cost_usd,0)) c, MIN(ts) t0, MAX(ts) t1 FROM agent_outputs WHERE run_id IN "
            "(SELECT run_id FROM agent_outputs WHERE node='dossier' AND status='ok' ORDER BY id DESC LIMIT 10) "
            "GROUP BY run_id").fetchall()
        costs = [r["c"] for r in rows if r["c"]]
        secs = []
        for r in rows:
            try:
                secs.append((datetime.fromisoformat(r["t1"]) - datetime.fromisoformat(r["t0"])).total_seconds())
            except (TypeError, ValueError):
                pass
        return {"usd": sum(costs) / len(costs) if costs else 1.0, "seconds": sum(secs) / len(secs) if secs else 120,
                "samples": len(costs)}

    # ------------------------------------------------------------------ analisar
    async def cmd_analisar(self, args: list[str], update_id: int | None = None, *, compact: bool = False,
                           quiet: bool = False) -> dict | None:
        version = None
        if args and args[-1].lower() in ("v1", "v2"):
            version, args = args[-1].lower(), args[:-1]
        query = re.sub(r"\s+", " ", " ".join(args)).strip()
        if not query:
            await self.say("Diz-me a ação: <code>/analisar AAPL</code> — ou escreve só o ticker ou o nome.")
            return None
        if not QUERY_RE.match(query):
            await self.say("Não percebi a ação. Usa só letras, números, espaços e pontos, até 40 caracteres "
                           "(ex.: <code>AAPL</code>, <code>005930.KS</code>, <code>Banco Comercial</code>).")
            return None
        version = version or jobs.setting(self.conn, "rating_version")
        job, state = jobs.enqueue(self.conn, "ticker", {"query": query, "version": version, "compact": compact},
                                  dedupe_key=f"ticker|{query.upper()}|{version}", update_id=update_id)
        if state == "seen":
            return job
        if state == "full":
            await self.say("A fila está cheia. Espera que algumas análises terminem (/estado) ou usa /cancelar.")
            return None
        if state == "duplicate":
            if not quiet:
                where = "já está a correr" if job["state"] == "running" else "já está em fila"
                await self.say(f"«{M.esc(query)}» {where} (tarefa #{job['id']}). Aviso-te quando terminar.")
            return job
        if not quiet:
            ahead = jobs.position(self.conn, job["id"])
            text = (f"⏳ <b>{M.esc(query)}</b> em fila: {ahead} análise{'s' if ahead != 1 else ''} à frente."
                    if ahead else f"⏳ <b>A analisar {M.esc(query)}</b>…")
            mid = await self.say(text, keyboard([[("✖️ Cancelar", f"x|{job['id']}")]]))
            jobs.update(self.conn, job["id"], status_msg_id=mid)
        self.wake.set()
        return job

    # ------------------------------------------------------------------ worker
    async def worker(self) -> None:
        while True:
            job = jobs.claim(self.conn)
            if job is None:
                self.wake.clear()
                try:
                    await asyncio.wait_for(self.wake.wait(), 20)   # acorda também para tarefas à espera do limite
                except asyncio.TimeoutError:
                    pass
                continue
            await self.run_job(job)

    async def run_job(self, job: dict) -> None:
        self.current, self.cancel = job, asyncio.Event()
        log.info("tarefa #%s %s %s (tentativa %s)", job["id"], job["kind"], job["args"], job["attempts"])
        try:
            if job["kind"] == "ticker":
                await self.run_ticker(job)
            elif job["kind"] == "ipos":
                await self.run_ipos(job)
            else:
                jobs.finish(self.conn, job["id"], "failed", error=f"tipo de tarefa desconhecido: {job['kind']}")
        except asyncio.CancelledError:
            raise                                      # o bot está a fechar: a tarefa fica `running` e é retomada
        except Exception as e:  # noqa: BLE001
            log.exception("tarefa #%s falhou", job["id"])
            jobs.finish(self.conn, job["id"], "failed", error=f"{type(e).__name__}: {e}")
            await self.edit(job.get("status_msg_id"),
                            "⚠️ A tarefa falhou por um erro interno. Ficou registado; toca em Repetir ou vê /estado.",
                            self._retry_kb(job), html=False)
        finally:
            self.current = self.cancel = self.progress = None

    def _retry_kb(self, job: dict) -> dict | None:
        q = (job.get("args") or {}).get("query")
        return keyboard([[("🔁 Repetir", f"y|{self.remember({'kind': 'ticker', 'query': q})}")]]) if q else None

    def _schedule_progress(self) -> None:
        if self.progress is None:
            return
        if self._edit_task is not None and not self._edit_task.done():
            self._edit_pending = True
            return
        self._edit_task = asyncio.create_task(self._edit_progress(self.progress))

    async def _edit_progress(self, prog: Progress) -> None:
        while self.progress is prog and self.current is not None:
            wait = EDIT_EVERY - (self.clock() - self._last_edit)
            if wait > 0:
                await asyncio.sleep(wait)
            if self.progress is not prog or self.current is None:
                return
            self._edit_pending = False
            behind = max(0, len(jobs.active(self.conn)) - 1)
            text = prog.text(behind)
            if text != self._last_text:
                mid = await self.edit(self.current.get("status_msg_id"), text,
                                      keyboard([[("✖️ Cancelar", f"x|{self.current['id']}")]]))
                if mid and mid != self.current.get("status_msg_id"):
                    self.current["status_msg_id"] = mid
                    jobs.update(self.conn, self.current["id"], status_msg_id=mid)
                self._last_text, self._last_edit = text, self.clock()
            if not self._edit_pending:
                return

    async def _pulse(self, job_id: int) -> None:
        """Enquanto a análise corre: sinal de vida na fila e ETA atualizado mesmo sem nós a terminar."""
        while True:
            await asyncio.sleep(8)
            jobs.beat(self.conn, job_id)
            if jobs.cancel_requested(self.conn, job_id) and self.cancel is not None:
                self.cancel.set()
            self._schedule_progress()

    def _company(self, run_id: str) -> str | None:
        row = self.conn.execute("SELECT output FROM agent_outputs WHERE run_id=? AND node='profile' AND status='ok'"
                                " ORDER BY id DESC LIMIT 1", (run_id,)).fetchone()
        if not row or not row["output"]:
            return None
        p = json.loads(row["output"])
        return f"{M.shorten(M.short_name(p.get('name')), 30)} ({p.get('symbol')})" if p.get("name") else None

    async def run_ticker(self, job: dict) -> None:
        args = job["args"]
        query, version = args["query"], args.get("version") or "v2"
        nodes = load_flow("ticker")
        order = [n for layer in layers(nodes) for n in layer]
        prog = self.progress = Progress(query, order, {n: deps(nodes[n], nodes) for n in order}, clock=self.clock)
        self._last_text, self._last_edit = "", 0.0
        resume = bool(job.get("run_id"))
        run_id = job.get("run_id") or new_run_id(query)
        jobs.update(self.conn, job["id"], run_id=run_id)

        def on_event(e: dict) -> None:
            prog.on_event(e)
            if e.get("node") == "profile" and e.get("type") == "done" and e.get("status") == "ok":
                prog.title = self._company(run_id) or prog.title
            self._schedule_progress()

        self._schedule_progress()
        pulse = asyncio.create_task(self._pulse(job["id"]))
        t0 = self.clock()
        try:
            rep = await self.runner("ticker", {"ticker": query, **rating_params(version), "alert_notify": False},
                                    run_id=run_id, on_event=on_event, cancel=self.cancel, resume=resume)
        finally:
            pulse.cancel()
            self.progress = None                        # nenhuma edição de progresso pode chegar depois do veredicto
            if self._edit_task is not None:
                self._edit_task.cancel()
        status = self.current.get("status_msg_id") if self.current else job.get("status_msg_id")
        title = self._company(run_id) or query
        problems = rep.problems()

        if rep.cancelled:
            jobs.finish(self.conn, job["id"], "cancelled", error="cancelada pelo utilizador")
            return void(await self.edit(status, M.esc(errors.humanize("cancelled", subject=title))))

        prof = rep.results.get("profile")
        if prof is None or prof.status != "ok":       # pedido ambíguo, inexistente ou deslistado: parou no perfil
            text, options = profile_error_text(query, prof.error if prof else "sem perfil")
            kb = keyboard([[(f"Analisar {o}", f"r|{o}")] for o in options[:5] if len(f"r|{o}".encode()) <= 64]) if options else None
            jobs.finish(self.conn, job["id"], "failed", error=(prof.error if prof else "sem perfil")[:500])
            return void(await self.edit(status, text, kb))

        guard = rep.results.get("guard")
        if guard is None or guard.status != "ok":
            node, err, kind = errors.root_cause(problems)
            log.error("tarefa #%s sem classificação: %s falhou: %s", job["id"], node, self.api.redact(err or ""))
            if kind == "limit":                        # espera pela reposição e retoma sozinho (os nós feitos ficam)
                when = errors.reset_time(err) or datetime.now(timezone.utc) + timedelta(minutes=30)
                jobs.wait_until(self.conn, job["id"], when, (err or "")[:300])
                kb = keyboard([[("🔁 Tentar já", f"q|{job['id']}"), ("✖️ Desistir", f"x|{job['id']}")]])
                return void(await self.edit(status, M.esc(errors.humanize("limit", subject=title, error=err, node=node)), kb))
            jobs.finish(self.conn, job["id"], "failed", error=f"{node}: {err}"[:500])
            return void(await self.edit(status, M.esc(errors.humanize(kind, subject=title, error=err, node=node)),
                                        self._retry_kb(job)))

        data = report_data.by_run(self.conn, run_id)
        if not data:
            jobs.finish(self.conn, job["id"], "failed", error="classificação não ficou gravada no histórico")
            return void(await self.edit(status, "⚠️ A análise terminou mas não ficou gravada. Vê /estado.",
                                        self._retry_kb(job), html=False))
        alert = rep.results.get("alert")
        change = alert.output if alert is not None and alert.status == "ok" and isinstance(alert.output, dict) else None
        gaps = [n for n in problems if n not in ("memory", "alert")]
        text = M.verdict(data, previous=report_data.previous(self.conn, data["run"]["ticker"], data["run"]["id"]),
                         change=change, gaps=len(gaps), total=len(rep.results),
                         note=getattr(prof.output, "resolution_note", None) if prof.output is not None else None)
        row_id = data["run"]["id"]
        if args.get("compact"):                        # lotes (universo, lista): só o texto, com os botões
            await self.edit(status, text, sections.buttons(row_id, data, actions=True))
        else:
            await self.edit(status, text)
            await self.tg(self.api.chat_action, "upload_photo")
            try:
                png = await asyncio.to_thread(sections.card_png, data)      # matplotlib fora do loop
                await self.tg(self.api.send_photo, png, sections.short_caption(data), True,
                              sections.buttons(row_id, data, actions=True))
            except Exception as e:  # noqa: BLE001 — a análise está paga: o veredicto já chegou, o cartão é extra
                log.error("cartão não enviado: %s", self.api.redact(e))
                await self.say("Não consegui enviar o cartão; o detalhe está nos botões.",
                               sections.buttons(row_id, data, actions=True))
        if change and change.get("alert_id"):
            self.conn.execute("UPDATE alerts SET sent=1 WHERE id=?", (change["alert_id"],))
            self.conn.commit()
        if gaps:
            log.warning("tarefa #%s com lacunas: %s", job["id"],
                        {n: self.api.redact(problems[n].error or "")[:200] for n in gaps})
        tok = rep.tokens()
        jobs.finish(self.conn, job["id"], "done", result={
            "run_id": run_id, "row_id": row_id, "ticker": data["run"]["ticker"], "rating": data["run"]["rating"],
            "cost_usd": round(rep.cost_usd, 4), "tokens": sum(tok.values()), "seconds": round(self.clock() - t0, 1),
            "gaps": gaps})

    async def run_ipos(self, job: dict) -> None:
        status = job.get("status_msg_id")
        rep = await self.runner("ipos", {"days": 30}, cancel=self.cancel)
        res = rep.results.get("calendar")
        if rep.cancelled:
            jobs.finish(self.conn, job["id"], "cancelled")
            return void(await self.edit(status, "🛑 Pesquisa de IPOs cancelada.", html=False))
        if not res or res.status != "ok":
            node, err, kind = errors.root_cause(rep.problems())
            jobs.finish(self.conn, job["id"], "failed", error=f"{node}: {err}"[:500])
            return void(await self.edit(status, M.esc(errors.humanize(kind, subject="", error=err, node=node))))
        ipos = res.output["ipos"]
        jobs.finish(self.conn, job["id"], "done", result={"ipos": len(ipos)})
        if not ipos:
            return void(await self.edit(status, "Sem IPOs relevantes nos próximos 30 dias.", html=False))
        await self.edit(status, M.new_ipos(ipos).replace("Novos IPOs no calendário", "IPOs nos próximos 30 dias"))

    # ------------------------------------------------------------------ comandos sobre o que já existe
    async def cmd_detalhe(self, args, _uid=None) -> None:
        t = resolve_ticker(self.conn, args[0]) if args else None
        if not t:
            return void(await self.say("Diz-me a ação: <code>/detalhe AAPL</code> (tem de já ter sido analisada)."))
        data = report_data.latest(self.conn, t)
        if not data or not data["outputs"]:
            return void(await self.say(f"Sem análise completa gravada para {M.esc(t)}.",
                                       keyboard([[(f"Analisar {t}", f"r|{t}")]])))
        prev = report_data.previous(self.conn, t, data["run"]["id"])
        await self.say(M.verdict(data, previous=prev, gaps=len(data["payload"].get("data_gaps") or [])))
        try:
            png = await asyncio.to_thread(sections.card_png, data)
            await self.tg(self.api.send_photo, png, sections.short_caption(data), True,
                          sections.buttons(data["run"]["id"], data, actions=True))
        except Exception as e:  # noqa: BLE001
            log.error("cartão não enviado: %s", self.api.redact(e))
            await self.say("O detalhe está nos botões.", sections.buttons(data["run"]["id"], data, actions=True))

    def history_text(self, ticker: str, limit: int = 10) -> str | None:
        rows = self.conn.execute("SELECT * FROM runs WHERE ticker=? ORDER BY id DESC LIMIT ?", (ticker, limit)).fetchall()
        if not rows:
            return None
        out = [f"📈 <b>Histórico</b> · {M.esc(ticker)}"]
        for r in rows:
            price = f"{M.price_pt(r['price'])} {r['currency'] or ''}".strip() if r["price"] is not None else "—"
            out.append(f"{M.EMOJI_RATING[r['rating']]} {M.esc(M.when_pt(r['ts']) or r['ts'][:10])} · "
                       f"{M.esc(Rating(r['rating']).label)} · {(r['confidence'] or 0):.0%} · {M.esc(price)}"
                       + (f" · {M.pct_pt(r['ret_30d'])} em 30 d" if r["ret_30d"] is not None else ""))
        return "\n".join(out)

    async def cmd_historico(self, args, _uid=None) -> None:
        if not args:
            return void(await self.say("Diz-me a ação: <code>/historico AAPL</code>."))
        t = resolve_ticker(self.conn, args[0]) or args[0].upper()
        text = self.history_text(t)
        if not text:
            return void(await self.say(f"Ainda não analisei {M.esc(t)}.", keyboard([[(f"Analisar {t}", f"r|{t}")]])))
        await self.say(text, keyboard([[("📄 Última análise", f"d|{t}"), ("🔁 Reanalisar", f"r|{t}")]]))

    # ------------------------------------------------------------------ lista e resumo
    def latest_row(self, ticker: str):
        return self.conn.execute("SELECT * FROM runs WHERE ticker=? ORDER BY id DESC LIMIT 1", (ticker,)).fetchone()

    async def cmd_seguir(self, args, _uid=None) -> None:
        if not args:
            return void(await self.say("Diz-me a ação: <code>/seguir AAPL</code>."))
        raw = " ".join(args)
        t = resolve_ticker(self.conn, raw) or raw.upper()
        if not QUERY_RE.match(t):
            return void(await self.say("Não percebi a ação."))
        row = self.latest_row(t)
        name = None
        if row and row["run_id"]:
            name = (report_data.run_outputs(self.conn, row["run_id"]).get("profile") or {}).get("name")
        added = jobs.watch_add(self.conn, t, name)
        await self.say(f"⭐ {M.esc(t)} {'entrou na' if added else 'já estava na'} tua lista. Vê /lista ou /hoje.")

    async def cmd_deixar(self, args, _uid=None) -> None:
        if not args:
            return void(await self.say("Diz-me a ação: <code>/deixar AAPL</code>."))
        t = resolve_ticker(self.conn, args[0]) or args[0].upper()
        removed = jobs.watch_remove(self.conn, t)
        await self.say(f"{M.esc(t)} {'saiu da' if removed else 'não estava na'} tua lista.")

    def list_text(self, title: str) -> tuple[str, dict | None]:
        wl = jobs.watchlist(self.conn)
        if not wl:
            return ("A tua lista está vazia. Junta ações com <code>/seguir AAPL</code> ou com o botão ⭐ de um cartão.",
                    None)
        lines, rows, old = [f"<b>{title}</b>"], [], 0
        for w in wl:
            r = self.latest_row(w["ticker"])
            if r is None:
                lines.append(f"⚪ <b>{M.esc(w['ticker'])}</b> — ainda sem análise")
                old += 1
            else:
                age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(r["ts"])).total_seconds() / 3600
                old += age_h > 20
                price = f"{M.price_pt(r['price'])} {r['currency'] or ''}".strip() if r["price"] is not None else ""
                lines.append(f"{M.EMOJI_RATING[r['rating']]} <b>{M.esc(w['ticker'])}</b> — {M.esc(Rating(r['rating']).label)} "
                             f"{(r['confidence'] or 0):.0%} · {M.esc(price)} · <i>{M.esc(M.when_pt(r['ts']) or '')}</i>")
            rows.append([(f"📄 {w['ticker']}", f"d|{w['ticker']}"), ("🗑", f"w|rm|{w['ticker']}")])
        est = self.estimate()
        if old:
            lines += ["", f"<i>{old} com mais de 20 h ou sem análise. Analisar todas: ~{M.num_pt(est['usd'] * len(wl), 2)} USD "
                          f"equivalentes, ~{M.duration_pt(est['seconds'] * len(wl))}.</i>"]
        rows = rows[:8] + [[("▶️ Analisar todas", "w|run")]]
        return "\n".join(lines), keyboard(rows)

    async def cmd_lista(self, _args=None, _uid=None) -> None:
        text, kb = self.list_text("⭐ A tua lista")
        await self.say(text, kb)

    async def cmd_hoje(self, _args=None, _uid=None) -> None:
        text, kb = self.list_text(f"🗓 Resumo de {M.when_pt(datetime.now(timezone.utc).isoformat(), False)}")
        await self.say(text, kb)

    async def cmd_comparar(self, args, _uid=None) -> None:
        if len(args) < 2:
            return void(await self.say("Diz-me duas ações já analisadas: <code>/comparar AAPL MSFT</code>."))
        pair, missing = [], []
        for a in args[:2]:
            t = resolve_ticker(self.conn, a)
            d = report_data.latest(self.conn, t) if t else None
            (pair if d and d["outputs"] else missing).append(d if d and d["outputs"] else a.upper())
        if missing:
            kb = keyboard([[(f"Analisar {m}", f"r|{m}")] for m in missing if len(f"r|{m}".encode()) <= 64])
            return void(await self.say("Ainda não analisei: " + ", ".join(M.esc(m) for m in missing) + ".", kb))

        def col(d):
            o, run = d["outputs"], d["run"]
            val = (o.get("fundamental_data") or {}).get("valuation") or {}
            ind, pt = o.get("indicators") or {}, o.get("price_targets") or {}
            fc = o.get("forecast") or {}
            exp = fc.get("expected_return_12m_pct")
            return [Rating(run["rating"]).label, f"{(run['confidence'] or 0):.0%}",
                    M.num_pt(val["forward_pe"], 1) if val.get("forward_pe") is not None else "—",
                    M.num_pt(val["ev_to_ebitda"], 1) if val.get("ev_to_ebitda") is not None else "—",
                    M.pct_pt((ind.get("returns_pct") or {}).get("1y"), 0) or "—",
                    M.pct_pt(pt.get("upside_mean_pct"), 0) or "—", M.pct_pt(exp, 0) or "—",
                    str((o.get("sentiment") or {}).get("score", "—")), str((o.get("timing") or {}).get("score", "—")),
                    M.when_pt(run["ts"], False) or ""]
        a, b = col(pair[0]), col(pair[1])
        labels = ["Classificação", "Confiança", "P/E 12 m", "EV/EBITDA", "Retorno 1 ano", "Alvo analistas", "Cenários 12 m",
                  "Sentimento", "Timing", "Analisada"]
        ta, tb = pair[0]["run"]["ticker"][:10], pair[1]["run"]["ticker"][:10]
        table = [f"{'':14}{ta:>11}{tb:>11}"] + [f"{lab:14}{x[:11]:>11}{y[:11]:>11}" for lab, x, y in zip(labels, a, b)]
        await self.say(f"⚖️ <b>{M.esc(ta)} vs {M.esc(tb)}</b>\n<pre>{M.esc(chr(10).join(table))}</pre>\n"
                       "<i>Sentimento e timing de −2 a +2. Alvo e cenários: variação face ao preço da análise.</i>",
                       keyboard([[(f"📄 {ta}", f"d|{pair[0]['run']['ticker']}"), (f"📄 {tb}", f"d|{pair[1]['run']['ticker']}")]]))

    # ------------------------------------------------------------------ IPOs e universo
    async def cmd_ipos(self, _args=None, update_id=None) -> None:
        job, state = jobs.enqueue(self.conn, "ipos", {}, dedupe_key="ipos", update_id=update_id)
        if state == "seen":
            return
        if state == "duplicate":
            return void(await self.say("Já estou a procurar os IPOs. Aviso-te quando terminar."))
        if state == "full":
            return void(await self.say("A fila está cheia. Vê /estado."))
        mid = await self.say("⏳ A procurar os IPOs dos próximos 30 dias…", keyboard([[("✖️ Cancelar", f"x|{job['id']}")]]))
        jobs.update(self.conn, job["id"], status_msg_id=mid)
        self.wake.set()

    async def cmd_ipo(self, args, _uid=None) -> None:
        if not args:
            return void(await self.say("Diz-me o IPO: <code>/ipo ANT</code> (símbolo, número ou nome). Vê /ipos."))
        await self.say(ipo_detail_text(self.conn, " ".join(args)))

    async def cmd_universo(self, args, _uid=None) -> None:
        try:
            n = max(1, min(50, int(args[0]))) if args else 10
        except ValueError:
            return void(await self.say("Diz-me quantas: <code>/universo 10</code> (máximo 50)."))
        path = ROOT / "data" / "universe.json"
        try:
            uni = json.loads(path.read_text(encoding="utf-8"))
            uni = uni.get("universe", uni) if isinstance(uni, dict) else uni
        except (OSError, ValueError):
            uni = []
        if not uni:
            return void(await self.say("Ainda não tenho a lista das maiores empresas. No PC, corre uma vez "
                                       "<code>python flow.py --universe --top 50</code> (só lista, não gasta LLM)."))
        top = [u["symbol"] for u in uni[:n] if u.get("symbol")]
        est = self.estimate()
        token = self.remember({"kind": "batch", "tickers": top})
        names = ", ".join(top[:8]) + ("…" if len(top) > 8 else "")
        await self.say(f"🌍 <b>As {len(top)} maiores</b>: {M.esc(names)}\n\n{len(top)} análises · cerca de "
                       f"<b>{M.num_pt(est['usd'] * len(top), 2)} USD</b> equivalentes da subscrição · "
                       f"~{M.duration_pt(est['seconds'] * len(top))}.\nCorrem uma de cada vez; recebes um resumo por ação.",
                       keyboard([[("✅ Confirmar", f"y|{token}"), ("Cancelar", "n")]]))

    # ------------------------------------------------------------------ definições, alertas, estado
    def _settings_view(self) -> tuple[str, dict]:
        ver = jobs.setting(self.conn, "rating_version")
        mark = lambda v: "✓ " if v == ver else ""  # noqa: E731
        text = ("⚙️ <b>Definições</b>\n\nClassificação: <b>" + ("v2 — com debate (a favor e contra)" if ver == "v2"
                else "v1 — um só analista, mais barata") + "</b>")
        return text, keyboard([[(f"{mark('v2')}v2 com debate", "f|ver|v2"), (f"{mark('v1')}v1 simples", "f|ver|v1")]])

    async def cmd_definicoes(self, _args=None, _uid=None) -> None:
        await self.say(*self._settings_view())

    def _alerts_view(self) -> tuple[str, dict]:
        auto, summ = jobs.setting(self.conn, "auto_analysis"), jobs.setting(self.conn, "daily_summary")
        hour, n = jobs.setting(self.conn, "summary_hour"), len(jobs.watchlist(self.conn))
        est = self.estimate()
        names = {"off": "desligadas", "fecho": "depois do fecho de cada bolsa", "abertura": "antes da abertura de cada bolsa",
                 "ambos": "antes da abertura e depois do fecho"}
        per_day = {"off": 0, "fecho": 1, "abertura": 1, "ambos": 2}[auto] * n
        text = ("🔔 <b>Alertas e horários</b>\n\n"
                f"Análises automáticas da tua lista ({n} ações): <b>{names[auto]}</b>\n"
                + (f"<i>≈ {per_day} análises por dia útil, ~{M.num_pt(per_day * est['usd'], 2)} USD equivalentes.</i>\n" if per_day else
                   "<i>Cada análise automática gasta utilização da subscrição do Claude.</i>\n")
                + f"\nResumo diário às {hour} (Lisboa): <b>{'ligado' if summ == 'on' else 'desligado'}</b>\n\n"
                "Só recebes alerta quando uma classificação muda de forma confirmada.")
        mark = lambda v: "✓ " if v == auto else ""  # noqa: E731
        return text, keyboard([[(f"{mark('off')}Desligadas", "f|auto|off"), (f"{mark('fecho')}Após o fecho", "f|auto|fecho")],
                               [(f"{mark('abertura')}Antes da abertura", "f|auto|abertura"), (f"{mark('ambos')}Ambos", "f|auto|ambos")],
                               [("Resumo diário: " + ("desligar" if summ == "on" else "ligar"), f"f|sum|{'off' if summ == 'on' else 'on'}")]])

    async def cmd_alertas(self, _args=None, _uid=None) -> None:
        await self.say(*self._alerts_view())

    def usage_today(self) -> dict:
        rows = self.conn.execute("SELECT run_id, node, cost_usd, usage FROM agent_outputs WHERE ts >= ?",
                                 (datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00"),)).fetchall()
        tokens = 0
        for r in rows:
            if r["usage"]:
                try:
                    tokens += sum(u.get(k, 0) for u in json.loads(r["usage"]).values()
                                  for k in ("input", "cache_write", "cache_read", "output"))
                except (ValueError, AttributeError):
                    pass
        return {"usd": sum(r["cost_usd"] or 0 for r in rows), "tokens": tokens,
                "analyses": len({r["run_id"] for r in rows if r["node"] == "guard"})}

    async def cmd_estado(self, _args=None, _uid=None) -> None:
        up = self.clock() - self.started
        lines = [f"🟢 <b>Agentock ligado</b> há {M.duration_pt(up) if up < 3600 else f'{up / 3600:.1f}'.replace('.', ',') + ' h'}"]
        act = jobs.active(self.conn)
        if not act:
            lines.append("Fila: vazia")
        for j in act[:6]:
            what = j["args"].get("query") or j["kind"]
            if j["state"] == "running":
                step = f" — {len(self.progress.done)} de {len(self.progress.order)} passos" if self.progress else ""
                lines.append(f"▶️ #{j['id']} {M.esc(what)}{step}")
            elif j["state"] == "waiting":
                when = datetime.fromisoformat(j["not_before"]) if j.get("not_before") else None
                lines.append(f"⏸️ #{j['id']} {M.esc(what)} — à espera do limite do Claude (até às {errors.hhmm(when)})")
            else:
                lines.append(f"⏳ #{j['id']} {M.esc(what)} — em fila")
        rec = jobs.recent(self.conn, 3)
        if rec:
            lines += ["", "<b>Últimas</b>"]
            for j in rec:
                res = json.loads(j["result"]) if j.get("result") else {}
                mark = {"done": "✅", "failed": "❌", "cancelled": "🛑"}.get(j["state"], "•")
                extra = (f" · {M.duration_pt(res['seconds'])} · {M.num_pt(res.get('cost_usd') or 0, 2)} USD"
                         if res.get("seconds") else "")
                err = f" · {M.esc(M.shorten(errors.humanize(errors.classify(j['error'])), 60))}" if j["state"] == "failed" and j.get("error") else ""
                lines.append(f"{mark} #{j['id']} {M.esc(j['args'].get('query') or j['kind'])}{extra}{err}")
        u = self.usage_today()
        auth = {"subscription": "subscrição do Claude", "api": "créditos da API"}.get(core.env.CLAUDE_AUTH, "omissão do SDK")
        size = db.DB_PATH.stat().st_size / 1e6 if db.DB_PATH.exists() else 0
        lines += ["", f"Hoje: {u['analyses']} análise{'s' if u['analyses'] != 1 else ''} · {M.num_pt(u['usd'], 2)} USD equivalentes"
                      + (f" · {M.num_pt(u['tokens'] / 1e6, 2)} M tokens" if u["tokens"] else ""),
                  f"Autenticação: {auth}", f"Base de dados: {M.num_pt(size, 1)} MB · última cópia: "
                  f"{M.when_pt(jobs.kv_get(self.conn, 'last_backup')) or 'ainda nenhuma'}"]
        await self.say("\n".join(lines))

    async def cmd_cancelar(self, _args=None, _uid=None) -> None:
        job = jobs.running(self.conn)
        if job is None:
            queued = [j for j in jobs.active(self.conn) if j["state"] != "running"]
            if not queued:
                return void(await self.say("Não há nenhuma análise a correr."))
            for j in queued:
                jobs.request_cancel(self.conn, j["id"])
            return void(await self.say(f"🛑 Tirei {len(queued)} tarefa{'s' if len(queued) != 1 else ''} da fila."))
        await self.cancel_job(job["id"])

    async def cancel_job(self, job_id: int) -> None:
        prev = jobs.request_cancel(self.conn, job_id)
        if prev == "running" and self.current and self.current["id"] == job_id and self.cancel is not None:
            self.cancel.set()                           # o worker edita a mensagem de estado quando parar
        elif prev in ("queued", "waiting"):
            j = jobs.get(self.conn, job_id)
            await self.edit(j.get("status_msg_id"), f"🛑 Tarefa #{job_id} cancelada.", html=False)
        elif prev is None or prev in ("done", "failed", "cancelled"):
            await self.say("Essa tarefa já tinha terminado.", html=False)

    # ------------------------------------------------------------------ botões
    async def on_callback(self, cq: dict) -> None:
        data = cq.get("data") or ""
        log.info("botão: %s", data)
        await self.tg(self.api.answer_callback, cq["id"])    # tira o "a carregar" do botão (ignora toques antigos)
        kind, _, rest = data.partition("|")
        msg_id = (cq.get("message") or {}).get("message_id")
        if kind == "s":
            return await self.show_section(data, cq.get("message") or {})
        if kind == "r" and rest:
            return void(await self.cmd_analisar([rest]))
        if kind == "d" and rest:
            return await self.cmd_detalhe([rest])
        if kind == "h" and rest:
            return await self.cmd_historico([rest])
        if kind == "x" and rest.isdigit():
            return await self.cancel_job(int(rest))
        if kind == "q" and rest.isdigit():
            j = jobs.get(self.conn, int(rest))
            if j and j["state"] == "waiting":
                jobs.update(self.conn, j["id"], state="queued", not_before=None)
                self.wake.set()
                return void(await self.say("A tentar outra vez…", html=False))
            return void(await self.say("Essa tarefa já não está à espera.", html=False))
        if kind == "w":
            op, _, t = rest.partition("|")
            if op == "add" and t:
                return await self.cmd_seguir([t])
            if op == "rm" and t:
                jobs.watch_remove(self.conn, t)
                text, kb = self.list_text("⭐ A tua lista")
                return void(await self.edit(msg_id, text, kb))
            if op == "run":
                wl = [w["ticker"] for w in jobs.watchlist(self.conn)]
                if not wl:
                    return void(await self.say("A tua lista está vazia."))
                est = self.estimate()
                token = self.remember({"kind": "batch", "tickers": wl})
                return void(await self.say(f"Analisar as {len(wl)} ações da lista? Cerca de <b>{M.num_pt(est['usd'] * len(wl), 2)} "
                                           f"USD</b> equivalentes · ~{M.duration_pt(est['seconds'] * len(wl))}.",
                                           keyboard([[("✅ Confirmar", f"y|{token}"), ("Cancelar", "n")]])))
        if kind == "f":
            name, _, value = rest.partition("|")
            if name == "ver" and value in ("v1", "v2"):
                jobs.set_setting(self.conn, "rating_version", value)
                return void(await self.edit(msg_id, *self._settings_view()))
            if name == "auto" and value in ("off", "fecho", "abertura", "ambos"):
                jobs.set_setting(self.conn, "auto_analysis", value)
                return void(await self.edit(msg_id, *self._alerts_view()))
            if name == "sum" and value in ("on", "off"):
                jobs.set_setting(self.conn, "daily_summary", value)
                return void(await self.edit(msg_id, *self._alerts_view()))
        if kind == "y" and rest:
            pending = jobs.kv_get(self.conn, f"confirm:{rest}")
            if not pending:
                return void(await self.edit(msg_id, "Esse pedido já foi tratado ou expirou.", html=False))
            self.conn.execute("DELETE FROM kv WHERE key=?", (f"confirm:{rest}",))
            self.conn.commit()
            if pending["kind"] == "ticker":
                await self.edit(msg_id, f"A analisar {pending['query']}…", html=False)
                return void(await self.cmd_analisar([pending["query"]], quiet=False))
            if pending["kind"] == "text":
                return await self.on_text(pending["text"])
            if pending["kind"] == "batch":
                n = 0
                for t in pending["tickers"]:
                    job = await self.cmd_analisar([t], compact=True, quiet=True)
                    n += job is not None
                return void(await self.edit(msg_id, f"✅ {n} análises em fila. Recebes um resumo por ação; "
                                                    "/estado mostra o andamento e /cancelar pára.", html=False))
        if kind == "n":
            return void(await self.edit(msg_id, "Ok, não faço nada.", html=False))
        await self.say("Este botão já não está disponível.", html=False)

    async def show_section(self, data: str, message: dict) -> None:
        """Uma só mensagem de detalhe por análise: tocar noutra secção edita-a em vez de encher a conversa."""
        text = sections.section(self.conn, data)
        parts = data.split("|")
        row_id = int(parts[1]) if len(parts) == 3 and parts[1].isdigit() else None
        kb = None
        if row_id is not None:
            row = self.conn.execute("SELECT * FROM runs WHERE id=?", (row_id,)).fetchone()
            if row:
                kb = sections.buttons(row_id, report_data.from_row(self.conn, row))
        if len(text) > 3800 or row_id is None:
            return void(await self.say(text, kb))
        key = f"detail_msg:{row_id}"
        current = message.get("message_id") if message.get("text") else jobs.kv_get(self.conn, key)
        mid = await self.edit(current, text, kb)
        if mid:
            jobs.kv_set(self.conn, key, mid)

    # ------------------------------------------------------------------ arranque, agendamentos, manutenção
    async def startup(self) -> None:
        rec = jobs.recover(self.conn)
        last = jobs.kv_get(self.conn, "last_heartbeat")
        clean = jobs.kv_get(self.conn, "clean_shutdown", True)
        jobs.kv_set(self.conn, "clean_shutdown", False)
        jobs.kv_set(self.conn, "pid", os.getpid())
        try:
            await self.tg(self.api.call, "setMyCommands", commands=json.dumps(
                [{"command": c, "description": d} for c, d in MENU]))
        except TelegramError as e:
            log.warning("não consegui registar o menu de comandos: %s", self.api.redact(e))
        lines = ["🟢 <b>Agentock ligado.</b>"]
        if last:
            lines[0] += f" Parado desde {M.esc(M.when_pt(last) or '')}" + ("." if clean else " — terminou de forma inesperada.")
        if rec["resumed"]:
            lines.append("A retomar: " + ", ".join(M.esc(j["args"].get("query") or j["kind"]) for j in rec["resumed"]) + ".")
        for j in rec["failed"]:
            lines.append(f"❌ {M.esc(j['args'].get('query') or j['kind'])} foi interrompida duas vezes e ficou por fazer.")
        waiting = [j for j in jobs.active(self.conn) if j["state"] != "running"]
        if waiting and not rec["resumed"]:
            lines.append(f"{len(waiting)} tarefa{'s' if len(waiting) != 1 else ''} em fila.")
        if not last:
            lines.append("Escreve um ticker ou um nome para analisar, ou vê /ajuda.")
        await self.say("\n".join(lines))   # aviso de arranque: sabes sempre quando o bot (re)começou
        self.wake.set()

    async def tick(self, now: datetime | None = None) -> None:
        """De minuto a minuto: sinal de vida, agendamentos e manutenção diária."""
        now = now or datetime.now(timezone.utc)
        jobs.kv_set(self.conn, "last_heartbeat", now.isoformat(timespec="seconds"))
        local = now.astimezone(M.LISBON)
        today = local.strftime("%Y-%m-%d")
        if jobs.setting(self.conn, "daily_summary") == "on" and local.strftime("%H:%M") >= jobs.setting(self.conn, "summary_hour") \
                and jobs.kv_get(self.conn, "summary_sent") != today and jobs.watchlist(self.conn):
            jobs.kv_set(self.conn, "summary_sent", today)
            await self.cmd_hoje()
        auto = jobs.setting(self.conn, "auto_analysis")
        if auto != "off":
            for t in self.due_auto(now, auto):
                await self.cmd_analisar([t], compact=True, quiet=True)
        if local.hour == 3 and jobs.kv_get(self.conn, "maintenance") != today:
            jobs.kv_set(self.conn, "maintenance", today)
            await asyncio.to_thread(self.maintenance)

    def due_auto(self, now: datetime, mode: str) -> list[str]:
        """Ações da lista a analisar agora: 30 min antes da abertura e/ou 15 min a 3 h depois do fecho da sua bolsa.
        Cada sessão só dispara uma vez (fica registado), por isso um reinício não repete análises."""
        from core.data.markets import calendar_code
        from core.sessions import market_state
        due = []
        for w in jobs.watchlist(self.conn):
            code = calendar_code(w["ticker"])
            if not code:
                continue
            try:
                st = market_state(code, now)
            except Exception:  # noqa: BLE001 — um calendário com problemas não pode parar os agendamentos
                log.exception("calendário %s", code)
                continue
            if mode in ("fecho", "ambos") and not st["open"]:
                closed = datetime.fromisoformat(st["last_close"])
                key = f"auto:{w['ticker']}:close"
                if timedelta(minutes=15) <= now - closed <= timedelta(hours=3) and jobs.kv_get(self.conn, key) != st["last_close"]:
                    jobs.kv_set(self.conn, key, st["last_close"])
                    due.append(w["ticker"])
                    continue
            if mode in ("abertura", "ambos") and not st["open"]:
                opens = datetime.fromisoformat(st["next_open"])
                key = f"auto:{w['ticker']}:open"
                if timedelta(0) <= opens - now <= timedelta(minutes=30) and jobs.kv_get(self.conn, key) != st["next_open"]:
                    jobs.kv_set(self.conn, key, st["next_open"])
                    due.append(w["ticker"])
        return due

    def maintenance(self) -> dict:
        """Cópia de segurança do histórico (14 dias) e limpeza de caches, tarefas e logs antigos."""
        import sqlite3
        conn = db.connect()
        out = {"prune": db.prune(conn), "jobs": jobs.prune(conn)}
        backups = ROOT / "data" / "backups"
        backups.mkdir(parents=True, exist_ok=True)
        target = backups / f"agentock-{datetime.now(M.LISBON):%Y%m%d}.db"
        if not target.exists():
            try:
                conn.execute("VACUUM INTO ?", (str(target),))
                jobs.kv_set(conn, "last_backup", jobs.now())
            except sqlite3.Error:
                log.exception("cópia de segurança falhou")
        for old in sorted(backups.glob("agentock-*.db"))[:-14]:
            old.unlink(missing_ok=True)
        limit = time.time() - 30 * 86400
        for folder in (ROOT / "data" / "logs", ROOT / "data" / "runs"):
            for p in folder.glob("*"):
                try:
                    if p.stat().st_mtime < limit and not p.name.startswith("bot.log"):
                        if p.is_dir():
                            import shutil
                            shutil.rmtree(p, ignore_errors=True)
                        else:
                            p.unlink()
                except OSError:
                    pass
        out["prewarm"] = self.prewarm()
        log.info("manutenção: %s", out)
        return out

    def prewarm(self) -> int:
        """Renova de madrugada os dados lentos das ações da lista (sem LLM, não gasta nada): na Coreia, os relatórios
        de insiders da DART demoram ~100 s por empresa e atrasariam a análise seguinte."""
        from core.data import DataUnavailable, get_router
        from core.data.markets import market_of
        n = 0
        for w in jobs.watchlist(db.connect()):
            if market_of(w["ticker"]) != "KR":
                continue
            try:
                get_router().get("insider_transactions", w["ticker"], use_cache=False, days=180)
                n += 1
            except DataUnavailable:
                pass
            except Exception:  # noqa: BLE001
                log.exception("pré-aquecimento de %s", w["ticker"])
        return n

    async def scheduler(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001
                log.exception("erro no agendador")
            await asyncio.sleep(60)

    async def poll(self) -> None:
        offset = jobs.kv_get(self.conn, "tg_offset", 0)
        allowed = json.dumps(["message", "edited_message", "callback_query"])
        while True:
            try:
                ups = (await self.tg(self.api.call, "getUpdates", 60, offset=offset, timeout=30,
                                     allowed_updates=allowed)).get("result") or []
            except TelegramError as e:
                if e.code == 409:   # outra instância a ler as mensagens: esta não pode continuar a disputar
                    log.error("outra instância do bot está ligada (409); a sair")
                    raise SystemExit(0) from None
                log.warning("getUpdates: %s", self.api.redact(e))
                await asyncio.sleep(5)
                continue
            for u in ups:
                offset = u["update_id"] + 1
                await self.on_update(u)
            await self.flush_stale()

    async def run(self) -> None:
        await self.startup()
        try:
            await asyncio.gather(self.poll(), self.worker(), self.scheduler())
        finally:
            jobs.kv_set(self.conn, "clean_shutdown", True)


def void(_x) -> None:
    """`return void(await …)`: sair de um handler depois de responder, sem devolver o id da mensagem."""
    return None


# ---------------------------------------------------------------------- processo
class Redact(logging.Filter):
    def __init__(self, secrets_: list[str]):
        super().__init__()
        self.secrets = [s for s in secrets_ if s and len(s) >= 8]

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for s in self.secrets:
            msg = msg.replace(s, "<segredo>")
        record.msg, record.args = msg, None
        return True


def setup_logging(token: str) -> None:
    logs = ROOT / "data" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    secrets_ = [token] + [v for k, v in os.environ.items() if k.endswith(("_KEY", "_TOKEN", "_SECRET", "_SECRET_KEY"))]
    handlers: list[logging.Handler] = [RotatingFileHandler(logs / "bot.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")]
    if sys.stdout is not None:                         # com pythonw não há consola
        handlers.append(logging.StreamHandler(sys.stdout))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in handlers:
        h.setFormatter(fmt)
        h.addFilter(Redact(secrets_))
        root.addHandler(h)


def single_instance():
    """Fica com o ficheiro data/bot.lock enquanto o processo viver. None se já houver outra instância."""
    path = ROOT / "data" / "bot.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+")  # noqa: SIM115 — tem de ficar aberto
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def main() -> None:
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8")
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        sys.exit("Falta TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID no .env (ver tools/telegram_setup.py)")
    setup_logging(token)
    lock = single_instance()
    if lock is None:
        log.info("já há um bot a correr (data/bot.lock); esta instância sai.")
        return
    users = {u.strip() for u in os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "").split(",") if u.strip()}
    log.info("bot a arrancar (pid %s)", os.getpid())
    try:
        asyncio.run(Bot(TelegramAPI(token, chat), allowed_users=users).run())
    except KeyboardInterrupt:
        log.info("bot parado.")
    finally:
        lock.close()


if __name__ == "__main__":
    main()
