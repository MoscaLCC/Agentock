"""Carrega o .env da raiz do projeto (importar antes de ler os.environ ou de lançar agentes LLM).

Autenticação do Claude (AGENTOCK_CLAUDE_AUTH no .env):
  subscription → o Agentock ignora a ANTHROPIC_API_KEY do ambiente (só no seu próprio processo e nos agentes
                 que lança), para o SDK usar o login do Claude Code (subscrição) em vez de créditos da API.
  api          → usa a ANTHROPIC_API_KEY (créditos da API).
  (omisso)     → comportamento normal do SDK.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH)

CLAUDE_AUTH = os.environ.get("AGENTOCK_CLAUDE_AUTH", "").strip().lower()
if CLAUDE_AUTH == "subscription":
    # não mexe nas variáveis do Windows, só neste processo e nos filhos; o AUTH_TOKEN tem precedência sobre tudo
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
