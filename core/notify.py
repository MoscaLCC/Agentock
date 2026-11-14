"""Notificações. Interface trocável; implementação Telegram + fallback consola.

Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID. O texto das mensagens é montado em core/messages.py.
"""
import html as _html
import json
import os
import re
import urllib.request
from typing import Protocol

DISCLAIMER = "Análise automática do Agentock — não é aconselhamento financeiro."


class Notifier(Protocol):
    def send(self, text: str, html: bool = False) -> bool: ...


def strip_html(text: str) -> str:
    return _html.unescape(re.sub(r"<[^>]+>", "", text))


class ConsoleNotifier:
    def send(self, text: str, html: bool = False) -> bool:
        print("[NOTIFY - consola, Telegram não configurado]\n" + (strip_html(text) if html else text))
        return False


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id

    def send(self, text: str, html: bool = False) -> bool:
        payload = {"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True}
        if html:
            payload["parse_mode"] = "HTML"
        req = urllib.request.Request(self.url, json.dumps(payload).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200


def default_notifier() -> Notifier:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    return TelegramNotifier(token, chat) if token and chat else ConsoleNotifier()
