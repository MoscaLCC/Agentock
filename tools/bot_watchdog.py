"""Vigia do bot: confirma o sinal de vida e desbloqueia-o se estiver preso.

  python tools/bot_watchdog.py          (corrido de 5 em 5 minutos pela tarefa "Agentock watchdog")

O bot grava `last_heartbeat` de minuto a minuto. O supervisor (tools/run_bot.cmd) só reage quando o processo
TERMINA; um processo preso (rede pendurada, bloqueio) continuaria "vivo" sem responder. Aqui:
  - sinal de vida com mais de STALE minutos e processo vivo → termina-o (o supervisor arranca outro) e avisa;
  - sem processo a correr há mais de STALE minutos → avisa uma vez (o supervisor não está ligado).
Só avisa uma vez por incidente (`kv.watchdog_alert`).
"""
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import core.env  # noqa: E402,F401
from core import db, jobs  # noqa: E402
from core.telegram import TelegramAPI, TelegramError  # noqa: E402

STALE_MINUTES = 6


def alive(pid: int | None) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"], capture_output=True, text=True).stdout
        return str(int(pid)) in out
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def kill(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(int(pid)), "/F", "/T"], capture_output=True)
    else:
        os.kill(int(pid), 9)


def check(conn, now: datetime | None = None, *, is_alive=alive, do_kill=kill) -> dict:
    """Decide o que fazer; devolve {"action": "ok" | "killed" | "down", "minutes": idade do sinal de vida}."""
    now = now or datetime.now(timezone.utc)
    last = jobs.kv_get(conn, "last_heartbeat")
    if not last:
        return {"action": "ok", "minutes": None}        # o bot nunca arrancou nesta máquina: nada a vigiar
    minutes = (now - datetime.fromisoformat(last)).total_seconds() / 60
    if minutes < STALE_MINUTES:
        if jobs.kv_get(conn, "watchdog_alert"):
            jobs.kv_set(conn, "watchdog_alert", None)   # recuperou: o próximo incidente volta a avisar
        return {"action": "ok", "minutes": minutes}
    pid = jobs.kv_get(conn, "pid")
    if is_alive(pid):
        do_kill(pid)
        action = "killed"
    else:
        action = "down"
    first = jobs.kv_get(conn, "watchdog_alert") != last
    jobs.kv_set(conn, "watchdog_alert", last)
    return {"action": action, "minutes": minutes, "notify": first}


def main() -> None:
    conn = db.connect()
    out = check(conn)
    if out["action"] == "ok" or not out.get("notify"):
        return
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    text = ("🔧 O bot do Agentock deixou de responder há {m:.0f} min; reiniciei-o. As tarefas em curso são retomadas."
            if out["action"] == "killed" else
            "🔴 O bot do Agentock está parado há {m:.0f} min e não há supervisor a arrancá-lo. "
            "No PC, corre tools\\start_bot.cmd (ou instala a tarefa: tools\\install_bot_task.ps1).").format(m=out["minutes"])
    try:
        TelegramAPI(token, chat).send_message(text)
    except TelegramError:
        pass


if __name__ == "__main__":
    main()
