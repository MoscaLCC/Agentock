"""Carrega o .env da raiz do projeto (importar antes de ler os.environ)."""
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH)
