"""Fase 9 — bot Telegram como trigger e como "detalhe a pedido" dos alertas compactos.

  python tools/telegram_bot.py        (fica a correr; Ctrl+C para parar)

Comandos (só do chat em TELEGRAM_CHAT_ID — mensagens de outros chats são ignoradas):
  /run TICKER [v1|v2]      análise completa; responde no formato compacto
  /detalhe_TICKER          razões e riscos completos da última classificação (ex.: /detalhe_005930_KS)
  /ipo_X                   análise completa de um IPO (símbolo ou nº), ex.: /ipo_ANT
  /status TICKER · /history TICKER · /ipos · /ajuda
Os comandos com "_" são tocáveis no Telegram (enviam-se inteiros). Só corre uma análise de cada vez.
"""
import asyncio
import json
import os
import sys
import traceback
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core.env  # noqa: E402,F401
from core import db, messages as M  # noqa: E402
from core.orchestrator import run_flow  # noqa: E402
from core.ratings import IpoRating, Rating  # noqa: E402
from core.schemas import IpoSynthesis  # noqa: E402

HELP = ("Comandos:\n/run TICKER [v1|v2] — análise completa\n/detalhe_TICKER — razões e riscos completos\n"
        "/ipo_SÍMBOLO — análise completa de um IPO\n/status TICKER · /history TICKER · /ipos")


def resolve_ticker(conn, arg: str) -> str | None:
    """'005930_KS' ou '005930.KS' → ticker gravado."""
    a = arg.strip().upper()
    for (t,) in conn.execute("SELECT DISTINCT ticker FROM runs").fetchall():
        if t.upper() == a or M.command_arg(t).upper() == a:
            return t
    return None


def detail_text(conn, ticker: str) -> str:
    r = conn.execute("SELECT * FROM runs WHERE ticker=? ORDER BY id DESC LIMIT 1", (ticker,)).fetchone()
    if not r:
        return f"Sem classificações para {M.esc(ticker)}."
    p = json.loads(r["payload"] or "{}")
    rating = Rating(r["rating"])
    price = f"{M.price_pt(r['price'])} {r['currency'] or ''}".strip() if r["price"] is not None else "—"
    lines = [f"{M.EMOJI_RATING[int(rating)]} <b>{M.esc(ticker)} — {M.esc(rating.label.upper())}</b> · "
             f"confiança {(r['confidence'] or 0):.0%} · {M.esc(r['version'] or 'v1')}",
             M.esc(f"{price} · {r['ts'][:16].replace('T', ' ')} UTC · horizonte {p.get('horizon') or '—'}")]
    if p.get("headline"):
        lines += ["", f"<i>{M.esc(p['headline'])}</i>"]
    lines += ["", "<b>Razões</b>"] + [f"{i}. {M.esc(x)}" for i, x in enumerate(json.loads(r["reasons"] or "[]"), 1)]
    if p.get("risks"):
        lines += ["", "<b>Riscos</b>"] + [f"• {M.esc(x)}" for x in p["risks"]]
    deb = p.get("debate") or {}
    if deb.get("bull") or deb.get("bear"):
        lines += ["", "<b>Debate</b>", f"👍 {M.esc(deb.get('bull') or '—')}", f"👎 {M.esc(deb.get('bear') or '—')}"]
    if p.get("warnings"):
        lines += ["", "⚠️ " + M.esc("; ".join(p["warnings"]))]
    if p.get("data_gaps"):
        lines.append(M.esc("Sem dados: " + ", ".join(p["data_gaps"])))
    lines += ["", f"<i>{M.DISCLAIMER_SHORT}</i>"]
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
    rating = IpoRating(row["rating"])
    head = M.ipo_rating(s, rating, None, None).split("\n")[:3]  # cabeçalho igual ao alerta
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
        self.base = f"https://api.telegram.org/bot{token}/"
        self.chat_id = str(chat_id)
        self.busy = asyncio.Lock()
        self.tasks: set[asyncio.Task] = set()  # referências às tarefas (evita recolha prematura)

    def _call(self, method: str, **params):
        data = urllib.parse.urlencode(params).encode()
        with urllib.request.urlopen(self.base + method, data, timeout=60) as r:
            return json.load(r)

    async def send(self, text: str, html: bool = True):
        # limite de 4096 caracteres: corta em linhas para não partir etiquetas HTML
        chunk = ""
        for line in text.split("\n"):
            if len(chunk) + len(line) + 1 > 3800 and chunk:
                await self._send_one(chunk, html)
                chunk = ""
            chunk += line + "\n"
        if chunk.strip():
            await self._send_one(chunk, html)

    async def _send_one(self, text: str, html: bool):
        params = {"chat_id": self.chat_id, "text": text, "disable_web_page_preview": "true"}
        if html:
            params["parse_mode"] = "HTML"
        await asyncio.to_thread(self._call, "sendMessage", **params)

    async def updates(self, offset: int):
        return (await asyncio.to_thread(self._call, "getUpdates", offset=offset, timeout=30)).get("result", [])

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
        g = rep.results.get("guard")
        if not g or g.status != "ok":
            return await self.send(f"{ticker}: a classificação falhou ({(g.error if g else 'sem guard')[:300]}).", html=False)
        s = g.output
        rating = Rating.parse(s.rating)
        price = f"{M.price_pt(s.price)} {s.currency or ''}".strip() if s.price is not None else None
        failed = [n for n, r in rep.results.items() if r.status != "ok"]
        lines = [f"{M.EMOJI_RATING[int(rating)]} <b>{M.esc(s.ticker)} — {M.esc(rating.label.upper())}</b>",
                 M.esc(" · ".join(x for x in (price, f"confiança {s.confidence:.0%}", s.version) if x)), ""]
        lines += [f"• {M.esc(M.shorten(p, 80))}" for p in (s.key_points or [M.first_clause(r) for r in s.reasons])[:3]]
        if failed:
            lines += ["", M.esc("Sem resultado: " + ", ".join(failed))]
        lines += [""] + M.footer(f"/detalhe_{M.command_arg(s.ticker)}")
        await self.send("\n".join(lines))

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

    async def set_menu(self):
        """Lista de comandos no botão "Menu" do Telegram."""
        cmds = [{"command": "run", "description": "Análise completa: /run AAPL"},
                {"command": "ipos", "description": "IPOs dos próximos 30 dias"},
                {"command": "status", "description": "Última classificação: /status AAPL"},
                {"command": "history", "description": "Histórico: /history AAPL"},
                {"command": "ajuda", "description": "Comandos disponíveis"}]
        await asyncio.to_thread(self._call, "setMyCommands", commands=json.dumps(cmds))

    async def handle(self, text: str):
        print(f"[{datetime.now():%H:%M:%S}] comando: {text}", flush=True)
        try:
            await self._handle(text)
            print(f"[{datetime.now():%H:%M:%S}] respondido: {text}", flush=True)
        except Exception as e:  # sem isto, um erro numa tarefa perdia-se em silêncio
            traceback.print_exc()
            await self.send(f"Erro ao processar {text}: {type(e).__name__}: {str(e)[:300]}", html=False)

    async def _handle(self, text: str):
        parts = text.strip().split()
        cmd, args = parts[0].split("@")[0], parts[1:]
        low = cmd.lower()
        if low.startswith("/detalhe"):
            arg = cmd[len("/detalhe_"):] if "_" in cmd else (args[0] if args else "")
            conn = db.connect()
            t = resolve_ticker(conn, arg) if arg else None
            await self.send(detail_text(conn, t) if t else "Uso: /detalhe_TICKER (ex.: /detalhe_AAPL)", html=bool(t))
        elif low.startswith("/ipo_") or (low == "/ipo" and args):
            arg = cmd[len("/ipo_"):] if low.startswith("/ipo_") else " ".join(args)
            await self.send(ipo_detail_text(db.connect(), arg))
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

    async def loop(self):
        offset = 0
        try:
            await self.set_menu()
        except Exception as e:
            print("aviso: não consegui registar o menu de comandos:", e, flush=True)
        print(f"[{datetime.now():%H:%M:%S}] Bot a correr. Ctrl+C para parar.", flush=True)
        while True:
            try:
                ups = await self.updates(offset)
            except Exception as e:  # rede: tenta de novo
                print("erro getUpdates:", e, flush=True)
                await asyncio.sleep(5)
                continue
            for u in ups:
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                if str((msg.get("chat") or {}).get("id")) != self.chat_id:
                    continue  # segurança: só o chat configurado
                if (msg.get("text") or "").startswith("/"):
                    task = asyncio.create_task(self.handle(msg["text"]))
                    self.tasks.add(task)
                    task.add_done_callback(self.tasks.discard)


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
