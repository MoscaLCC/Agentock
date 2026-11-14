"""Utilitários partilhados pelos agentes de script."""
from datetime import date, datetime

from pydantic import BaseModel

# índice de referência por mercado (retornos em excesso, momentum relativo)
BENCHMARK = {"US": "^GSPC", "KR": "^KS11", "JP": "^N225", "HK": "^HSI", "CN": "000001.SS", "EU": "^STOXX50E"}


def as_dict(x):
    """Aceita o output de outro nó (modelo pydantic, dict ou None) e devolve dict/None."""
    if x is None:
        return None
    if isinstance(x, BaseModel):
        return x.model_dump(mode="json")
    return x


def days_between(a: str | date, b: str | date | None = None) -> int:
    a = date.fromisoformat(str(a)[:10]) if not isinstance(a, date) else a
    b = date.today() if b is None else (date.fromisoformat(str(b)[:10]) if not isinstance(b, date) else b)
    return (b - a).days


def r2(x, nd: int = 2):
    return None if x is None else round(float(x), nd)


def now_utc() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
