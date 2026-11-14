"""Fase 9 — bot Telegram: trigger das análises e "detalhe a pedido" dos alertas.

  python tools/telegram_bot.py        (fica a correr; Ctrl+C para parar)

Comandos (só do chat em TELEGRAM_CHAT_ID — mensagens e toques de outros chats são ignorados):
  /run TICKER [v1|v2]   análise completa → cartão (imagem + resumo + botões)
  /detalhe_TICKER       cartão da última análise (ex.: /detalhe_005930_KS)
  /ipo_X                análise completa de um IPO (símbolo ou nº), ex.: /ipo_ANT
  /status TICKER · /history TICKER · /ipos · /ajuda
Botões do cartão: Razões · Riscos · Debate · Peers · Cenários · Notícias (cada um abre só essa secção).
Só corre uma análise de cada vez.
"""
import asyncio
import json
import os
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core.env  # noqa: E402,F401
from core import db, messages as M, report_data, sections  # noqa: E402
from core.orchestrator import run_flow  # noqa: E402
from core.ratings import IpoRating, Rating  # noqa: E402
from core.schemas import IpoSynthesis  # noqa: E402
from core.telegram import TelegramAPI  # noqa: E402

HELP = ("Comandos:\n/run TICKER [v1|v2] — análise completa\n/detalhe_TICKER — cartão da última análise\n"
        "/ipo_SÍMBOLO — análise completa de um IPO\n/status TICKER · /history TICKER · /ipos")


def resolve_ticker(conn, arg: str) -> str | None:
    """'005930_KS' ou '005930.KS' → ticker gravado."""
    a = arg.strip().upper()
    for (t,) in conn.execute("SELECT DISTINCT ticker FROM runs").fetchall():
        if t.upper() == a or M.command_arg(t).upper() == a:
            return t
    return None


def run_command(symbol: str) -> str:
    return f"/run_{M.command_arg(symbol)}"


def symbol_from_command(arg: str) -> str:
    """'005930_KS' → '005930.KS' (o último '_' antes de um sufixo de bolsa volta a ser '.')."""
    m = re.fullmatch(r"(.+)_([A-Z]{1,3})", arg.upper())
    return f"{m.group(1)}.{m.group(2)}" if m else arg.upper()


def profile_error_text(query: str, error: str) -> str:
    """Erro do perfil (ambíguo / sem cotação ativa) com as opções em comandos tocáveis."""
    msg = re.sub(r"^ValueError:\s*", "", error or "")
    options = re.findall(r"→ ([A-Z0-9.\-^=]+)", msg)
    lines = [f"⚠️ <b>Não analisei '{M.esc(query)}'</b>", M.esc(M.shorten(msg, 400))]
    if options:
        lines += ["", "Escolhe:"] + [run_command(o) for o in dict.fromkeys(options)]
    return "\n".join(lines)


def ipo_detail_text(conn, arg: str) -> str:
    a = arg.strip()
    rows = conn.execute("SELECT * FROM ipo_ratings ORDER BY id DESC").fetchall()
    row = next((r for r in rows if a.isdigit() and r["id"] == int(a)), None) or \
        next((r for r in rows if r["symbol"] and M.command_arg(r["symbol"]).upper() == a.upper()), None) or \
        next((r for r in rows if a.lower() in (r["name"] or "").lower()), None)
    if not row:
        return f"Sem análise de IPO para {M.esc(a)}."
    s = IpoSynthesis.model_validate(json.loads(row["payload"]))
    head = M.ipo_rating(s, IpoRating(row["rating"]), None, None).split("\n")[:3]  # cabeçalho igual ao alerta
    sec = lambda title, items: (["", f"<b>{title}</b>"] + [f"• {M.esc(x)}" for x in items]) if items else []  # noqa: E731
    lines = head + ([f"<i>{M.esc(s.headline)}</i>"] if s.headline else [])
    lines += ["", "<b>Valorização</b>", M.esc(M.shorten(s.valuation_view, 700)),
              "", "<b>Financeiras</b>", M.esc(M.shorten(s.financials, 600)),
              "", "<b>Janela de IPOs</b>", M.esc(M.shorten(s.ipo_window, 400))]
    lines += sec("A favor", s.bull_case) + sec("Contra", s.bear_case) + sec("Por divulgar", s.not_disclosed) + \
        sec("A acompanhar", s.watch_points) + sec("Fontes", s.sources[:4])
    return "\n".join(lines + ["", f"<i>{M.DISCLAIMER_SHORT}</i>"])


class Bot:
    def __init__(self, token: str, chat_id: str):
        self.api = TelegramAPI(token, chat_id)
        self.chat_id = str(chat_id)
        self.busy = asyncio.Lock()
        self.tasks: set[asyncio.Task] = set()  # referências às tarefas (evita recolha prematura)

    async def send(self, text: str, html: bool = True):
        # limite de 4096 caracteres: corta em linhas para não partir etiquetas HTML
        chunk = ""
        for line in text.split("\n"):
            if len(chunk) + len(line) + 1 > 3800 and chunk:
                await asyncio.to_thread(self.api.send_message, chunk, html)
                chunk = ""
            chunk += line + "\n"
        if chunk.strip():
            await asyncio.to_thread(self.api.send_message, chunk, html)

    async def send_card(self, data: dict, note: str | None = None):
        png = await asyncio.to_thread(sections.card_png, data)  # matplotlib fora do loop
        await asyncio.to_thread(self.api.send_photo, png, sections.caption(data, note), True,
                                sections.buttons(data["run"]["id"]))

    # ---------------------------------------------------------- comandos
    async def cmd_run(self, args):
        if not args:
            return await self.send("Uso: /run TICKER [v1|v2]", html=False)
        if self.busy.locked():
            return await self.send("Já há uma análise a correr; espera que termine.", html=False)
        ticker, ver = args[0], (args[1] if len(args) > 1 and args[1] in ("v1", "v2") else "v2")
        await self.send(f"⏳ A analisar {ticker} (classificação {ver})… demora alguns minutos.", html=False)
        async with self.busy:
            agent = "rating_agent" if ver == "v2" else "rating_v1_agent"
            rep = await run_flow("ticker", {"ticker": ticker, "rating_agent": agent, "rating_version": ver})
        prof = rep.results.get("profile")
        if not prof or prof.status != "ok":  # pedido ambíguo, inexistente ou deslistado: o fluxo parou no perfil
            return await self.send(profile_error_text(ticker, prof.error if prof else "sem perfil"))
        g = rep.results.get("guard")
        if not g or g.status != "ok":
            return await self.send(f"{ticker}: a classificação falhou ({(g.error if g else 'sem guard')[:300]}).", html=False)
        data = report_data.by_run(db.connect(), g.output.run_id)
        if data:
            await self.send_card(data, getattr(prof.output, "resolution_note", None))
        failed = [n for n, r in rep.results.items() if r.status != "ok"]
        if failed:
            await self.send(M.esc(f"Sem resultado nesta análise: {', '.join(failed)}"))

    async def cmd_detail(self, arg: str):
        conn = db.connect()
        t = resolve_ticker(conn, arg) if arg else None
        if not t:
            return await self.send("Uso: /detalhe_TICKER (ex.: /detalhe_AAPL)", html=False)
        data = report_data.latest(conn, t)
        if not data or not data["outputs"]:
            return await self.send(f"Sem análise completa gravada para {t}.", html=False)
        await self.send_card(data)

    async def cmd_status(self, args, limit=1):
        if not args:
            return await self.send("Uso: /status TICKER", html=False)
        conn = db.connect()
        t = resolve_ticker(conn, args[0]) or args[0].upper()
        rows = conn.execute("SELECT * FROM runs WHERE ticker=? ORDER BY id DESC LIMIT ?", (t, limit)).fetchall()
        if not rows:
            return await self.send(f"Sem classificações para {t}.", html=False)
        out = [f"<b>{M.esc(t)}</b>"] + [
            f"{M.EMOJI_RATING[r['rating']]} {M.esc(M.date_pt(r['ts']) or r['ts'][:10])} · {M.esc(Rating(r['rating']).label)} · "
            f"{(r['confidence'] or 0):.0%} · {M.esc(M.price_pt(r['price']) or '—')} · {M.esc(r['version'] or 'v1')}"
            for r in rows]
        await self.send("\n".join(out + ["", f"Detalhes: /detalhe_{M.command_arg(t)}"]))

    async def cmd_ipos(self, _args):
        rep = await run_flow("ipos", {"days": 30})
        res = rep.results.get("calendar")
        if not res or res.status != "ok":
            return await self.send("Calendário de IPOs indisponível.", html=False)
        ipos = res.output["ipos"]
        if not ipos:
            return await self.send("Sem IPOs relevantes nos próximos 30 dias.", html=False)
        await self.send(M.new_ipos(ipos).replace("Novos IPOs no calendário", "IPOs nos próximos 30 dias"))

    async def on_callback(self, cq: dict):
        await asyncio.to_thread(self.api.answer_callback, cq["id"])  # tira o "a carregar" do botão
        data = cq.get("data") or ""
        if data.startswith("s|"):
            await self.send(sections.section(db.connect(), data))

    # ---------------------------------------------------------- despacho
    async def handle(self, text: str):
        print(f"[{datetime.now():%H:%M:%S}] comando: {text}", flush=True)
        try:
            await self._handle(text)
            print(f"[{datetime.now():%H:%M:%S}] respondido: {text}", flush=True)
        except Exception as e:  # sem isto, um erro numa tarefa perdia-se em silêncio
            traceback.print_exc()
            await self.send(f"Erro ao processar {text}: {type(e).__name__}: {str(e)[:300]}", html=False)

    async def handle_callback(self, cq: dict):
        print(f"[{datetime.now():%H:%M:%S}] botão: {cq.get('data')}", flush=True)
        try:
            await self.on_callback(cq)
        except Exception as e:
            traceback.print_exc()
            await self.send(f"Erro no botão: {type(e).__name__}: {str(e)[:300]}", html=False)

    async def _handle(self, text: str):
        parts = text.strip().split()
        cmd, args = parts[0].split("@")[0], parts[1:]
        low = cmd.lower()
        if low.startswith("/detalhe"):
            await self.cmd_detail(cmd[len("/detalhe_"):] if "_" in cmd else (args[0] if args else ""))
        elif low.startswith("/ipo_") or (low == "/ipo" and args):
            arg = cmd[len("/ipo_"):] if low.startswith("/ipo_") else " ".join(args)
            await self.send(ipo_detail_text(db.connect(), arg))
        elif low.startswith("/run_"):  # versão tocável: /run_005930_KS
            await self.cmd_run([symbol_from_command(cmd[len("/run_"):])] + args)
        elif low == "/run":
            await self.cmd_run(args)
        elif low == "/status":
            await self.cmd_status(args)
        elif low == "/history":
            await self.cmd_status(args, limit=10)
        elif low == "/ipos":
            await self.cmd_ipos(args)
        else:  # /ajuda, /start, ou comando desconhecido
            await self.send(HELP, html=False)

    async def set_menu(self):
        """Lista de comandos no botão "Menu" do Telegram."""
        cmds = [{"command": "run", "description": "Análise completa: /run AAPL"},
                {"command": "ipos", "description": "IPOs dos próximos 30 dias"},
                {"command": "status", "description": "Última classificação: /status AAPL"},
                {"command": "history", "description": "Histórico: /history AAPL"},
                {"command": "ajuda", "description": "Comandos disponíveis"}]
        await asyncio.to_thread(self.api.call, "setMyCommands", commands=json.dumps(cmds))

    def _spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def loop(self):
        offset = 0
        try:
            await self.set_menu()
        except Exception as e:
            print("aviso: não consegui registar o menu de comandos:", e, flush=True)
        print(f"[{datetime.now():%H:%M:%S}] Bot a correr. Ctrl+C para parar.", flush=True)
        while True:
            try:
                ups = (await asyncio.to_thread(self.api.call, "getUpdates", http_timeout=60, offset=offset,
                                               timeout=30)).get("result", [])
            except Exception as e:  # rede: tenta de novo
                print("erro getUpdates:", e, flush=True)
                await asyncio.sleep(5)
                continue
            for u in ups:
                offset = u["update_id"] + 1
                if "callback_query" in u:
                    cq = u["callback_query"]
                    if str(((cq.get("message") or {}).get("chat") or {}).get("id")) == self.chat_id:
                        self._spawn(self.handle_callback(cq))
                    continue
                msg = u.get("message") or {}
                if str((msg.get("chat") or {}).get("id")) != self.chat_id:
                    continue  # segurança: só o chat configurado
                if (msg.get("text") or "").startswith("/"):
                    self._spawn(self.handle(msg["text"]))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        sys.exit("Falta TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID no .env (ver tools/telegram_setup.py)")
    try:
        asyncio.run(Bot(token, chat).loop())
    except KeyboardInterrupt:
        print("Bot parado.")


if __name__ == "__main__":
    main()
