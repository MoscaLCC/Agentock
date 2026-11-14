"""Fase 9 — bot Telegram como trigger.

  python tools/telegram_bot.py        (fica a correr; Ctrl+C para parar)

Comandos (só do chat em TELEGRAM_CHAT_ID — mensagens de outros chats são ignoradas):
  /run TICKER [v1|v2]   corre o fluxo completo e responde com a classificação
  /status TICKER        última classificação gravada
  /history TICKER       últimas 10 classificações
  /ipos                 IPOs dos próximos 30 dias
  /ajuda
Só corre uma análise de cada vez (controlo de custo).
"""
import asyncio
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core.env  # noqa: E402,F401
from core import db  # noqa: E402
from core.notify import DISCLAIMER  # noqa: E402
from core.orchestrator import run_flow  # noqa: E402
from core.ratings import Rating  # noqa: E402

HELP = ("Comandos:\n/run TICKER [v1|v2] — análise completa\n/status TICKER — última classificação\n"
        "/history TICKER — últimas 10\n/ipos — IPOs dos próximos 30 dias\n/ajuda")


class Bot:
    def __init__(self, token: str, chat_id: str):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.chat_id = str(chat_id)
        self.busy = asyncio.Lock()

    def _call(self, method: str, **params):
        data = urllib.parse.urlencode(params).encode()
        with urllib.request.urlopen(self.base + method, data, timeout=60) as r:
            return json.load(r)

    async def send(self, text: str):
        for i in range(0, len(text), 3900):  # limite de 4096 caracteres por mensagem
            await asyncio.to_thread(self._call, "sendMessage", chat_id=self.chat_id, text=text[i:i + 3900])

    async def updates(self, offset: int):
        return (await asyncio.to_thread(self._call, "getUpdates", offset=offset, timeout=30)).get("result", [])

    # ---------------------------------------------------------- comandos
    async def cmd_run(self, args):
        if not args:
            return await self.send("Uso: /run TICKER [v1|v2]")
        if self.busy.locked():
            return await self.send("Já há uma análise a correr; espera que termine.")
        ticker, ver = args[0], (args[1] if len(args) > 1 and args[1] in ("v1", "v2") else "v2")
        await self.send(f"A analisar {ticker} (classificação {ver})… demora alguns minutos.")
        async with self.busy:
            agent = "rating_agent" if ver == "v2" else "rating_v1_agent"
            rep = await run_flow("ticker", {"ticker": ticker, "rating_agent": agent, "rating_version": ver})
        g = rep.results.get("guard")
        failed = [n for n, r in rep.results.items() if r.status != "ok"]
        if not g or g.status != "ok":
            return await self.send(f"{ticker}: a classificação falhou ({(g.error if g else 'sem guard')[:300]}).")
        s = g.output
        lines = [f"{s.ticker}: {Rating.parse(s.rating).label} · confiança {s.confidence:.0%} · preço {s.price} {s.currency or ''}",
                 *[f"- {x}" for x in s.reasons[:4]], f"Custo: {rep.cost_usd:.2f} USD"]
        if failed:
            lines.append("Nós sem resultado: " + ", ".join(failed))
        if s.warnings:
            lines.append("Avisos: " + "; ".join(s.warnings))
        lines.append(DISCLAIMER)
        await self.send("\n".join(lines))

    async def cmd_status(self, args, limit=1):
        if not args:
            return await self.send("Uso: /status TICKER")
        rows = db.connect().execute("SELECT * FROM runs WHERE ticker=? ORDER BY id DESC LIMIT ?",
                                    (args[0].upper(), limit)).fetchall()
        if not rows:
            return await self.send(f"Sem classificações para {args[0].upper()}.")
        await self.send("\n".join(f"{r['ts'][:16].replace('T', ' ')} · {Rating(r['rating']).label} · "
                                  f"{(r['confidence'] or 0):.0%} · {r['price']} · {r['version'] or 'v1'}" for r in rows))

    async def cmd_ipos(self, _args):
        rep = await run_flow("ipos", {"days": 30})
        res = rep.results.get("calendar")
        if not res or res.status != "ok":
            return await self.send("Calendário de IPOs indisponível.")
        ipos = res.output["ipos"]
        await self.send("\n".join([f"IPOs nos próximos 30 dias ({len(ipos)}):"] +
                                  [f"- {i.get('date')} {i.get('name')} ({i.get('symbol') or '—'}) {i.get('price_range') or ''}"
                                   for i in ipos[:15]]) or "Sem IPOs.")

    async def handle(self, text: str):
        parts = text.strip().split()
        cmd, args = parts[0].lower().split("@")[0], parts[1:]
        if cmd == "/run":
            await self.cmd_run(args)
        elif cmd == "/status":
            await self.cmd_status(args)
        elif cmd == "/history":
            await self.cmd_status(args, limit=10)
        elif cmd == "/ipos":
            await self.cmd_ipos(args)
        else:
            await self.send(HELP)

    async def loop(self):
        offset = 0
        print("Bot a correr. Ctrl+C para parar.")
        while True:
            try:
                ups = await self.updates(offset)
            except Exception as e:  # rede: tenta de novo
                print("erro getUpdates:", e)
                await asyncio.sleep(5)
                continue
            for u in ups:
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                if str((msg.get("chat") or {}).get("id")) != self.chat_id:
                    continue  # segurança: só o chat configurado
                if (msg.get("text") or "").startswith("/"):
                    asyncio.create_task(self.handle(msg["text"]))


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
