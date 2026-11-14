"""Notificações. Interface trocável; implementação Telegram + fallback consola.

Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""
import json
import os
import urllib.request
from typing import Protocol

from .changes import Change


class Notifier(Protocol):
    def send(self, text: str) -> bool: ...


class ConsoleNotifier:
    def send(self, text: str) -> bool:
        print("[NOTIFY - consola, Telegram não configurado]\n" + text)
        return False


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id

    def send(self, text: str) -> bool:
        body = json.dumps({"chat_id": self.chat_id, "text": text}).encode()
        req = urllib.request.Request(self.url, body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200


def default_notifier() -> Notifier:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    return TelegramNotifier(token, chat) if token and chat else ConsoleNotifier()


DISCLAIMER = "Análise automática do Agentock — não é aconselhamento financeiro."


def format_change(c: Change, price=None, confidence=None, reasons=None, diff: dict | None = None,
                  version: str | None = None, currency: str | None = None, warnings: list | None = None) -> str:
    arrow = "SUBIU" if c.delta > 0 else "DESCEU"
    lines = [f"{c.ticker}: {c.old.label} -> {c.new.label} ({arrow} {abs(c.delta)} nível(is))"]
    if price is not None:
        lines.append(f"Preço: {price:,.2f} {currency or ''}".rstrip())
    if confidence is not None:
        lines.append(f"Confiança: {confidence:.0%}" + (f" · classificação {version}" if version else ""))
    if c.kind == "confirmed":
        lines.append("(mudança confirmada em execuções consecutivas)")
    if reasons:
        lines.append("Razões:")
        lines += [f"- {r}" for r in reasons]
    if diff and (diff.get("added") or diff.get("removed")):
        lines.append("O que mudou face à classificação anterior:")
        lines += [f"+ {r}" for r in diff.get("added", [])]
        lines += [f"− {r}" for r in diff.get("removed", [])]
    if warnings:
        lines.append("Avisos: " + "; ".join(warnings))
    lines.append(DISCLAIMER)
    return "\n".join(lines)
