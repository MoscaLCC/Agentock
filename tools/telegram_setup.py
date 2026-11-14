"""Configuração do Telegram, passo a passo.

  python tools/telegram_setup.py          # diz o que falta / mostra o chat id / envia teste
  python tools/telegram_setup.py --save   # grava o chat id encontrado no .env
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.env import ENV_PATH  # noqa: E402  (carrega o .env)
from core.notify import TelegramNotifier  # noqa: E402


def api(token: str, method: str) -> dict:
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{method}", timeout=15) as r:
        return json.load(r)


def save_chat_id(chat_id: int) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    lines = [l for l in lines if not l.startswith("TELEGRAM_CHAT_ID=")] + [f"TELEGRAM_CHAT_ID={chat_id}"]
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    token, chat_id = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")

    if not token:
        print("Falta TELEGRAM_BOT_TOKEN no .env.\n"
              "1) No Telegram, abre @BotFather e envia /newbot\n"
              "2) Copia o token que ele te der para o .env: TELEGRAM_BOT_TOKEN=...\n"
              "3) Volta a correr este script.")
        return

    me = api(token, "getMe")["result"]
    print(f"Bot OK: @{me['username']}")

    if not chat_id:
        chats = {u["message"]["chat"]["id"]: u["message"]["chat"].get("first_name", "")
                 for u in api(token, "getUpdates").get("result", []) if "message" in u}
        if not chats:
            print(f"Ainda não há mensagens. Abre https://t.me/{me['username']}, carrega em Iniciar/Start, "
                  "envia 'olá' e volta a correr este script.")
            return
        for cid, name in chats.items():
            print(f"Chat encontrado: {cid} ({name})")
        cid = next(iter(chats))
        if "--save" in sys.argv:
            save_chat_id(cid)
            chat_id = str(cid)
            print(f"TELEGRAM_CHAT_ID={cid} gravado no .env")
        else:
            print("Corre com --save para gravar no .env.")
            return

    ok = TelegramNotifier(token, chat_id).send("Agentock: Telegram configurado com sucesso.")
    print("Mensagem de teste enviada." if ok else "Falhou o envio da mensagem de teste.")


if __name__ == "__main__":
    main()
