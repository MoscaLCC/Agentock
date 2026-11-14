"""Notificações. Interface trocável; implementação Telegram + fallback consola.

Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID. Texto das mensagens: core/messages.py; cartão: core/sections.py.
"""
import html as _html
import os
import re
from pathlib import Path
from typing import Protocol

from .telegram import TelegramAPI

DISCLAIMER = "Análise automática do Agentock — não é aconselhamento financeiro."
REPORTS = Path(__file__).resolve().parent.parent / "data" / "reports"


class Notifier(Protocol):
    def send(self, text: str, html: bool = False) -> bool: ...

    def send_photo(self, png: bytes, caption: str, html: bool = False, buttons: dict | None = None) -> bool: ...


def strip_html(text: str) -> str:
    return _html.unescape(re.sub(r"<[^>]+>", "", text))


class ConsoleNotifier:
    def send(self, text: str, html: bool = False) -> bool:
        print("[NOTIFY - consola, Telegram não configurado]\n" + (strip_html(text) if html else text))
        return False

    def send_photo(self, png: bytes, caption: str, html: bool = False, buttons: dict | None = None) -> bool:
        REPORTS.mkdir(parents=True, exist_ok=True)
        path = REPORTS / "ultimo_cartao.png"
        path.write_bytes(png)
        labels = " · ".join(b["text"] for row in (buttons or {}).get("inline_keyboard", []) for b in row)
        return self.send(f"[cartão gravado em {path}]\n{caption}" + (f"\n[botões: {labels}]" if labels else ""), html)


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.api = TelegramAPI(token, chat_id)

    def send(self, text: str, html: bool = False) -> bool:
        return self.api.send_message(text, html)

    def send_photo(self, png: bytes, caption: str, html: bool = False, buttons: dict | None = None) -> bool:
        return self.api.send_photo(png, caption, html, buttons)


def default_notifier() -> Notifier:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    return TelegramNotifier(token, chat) if token and chat else ConsoleNotifier()
