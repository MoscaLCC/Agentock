"""Utilitários partilhados pelos agentes de script."""
from datetime import date, datetime

from pydantic import BaseModel

# índice de referência por mercado (retornos em excesso, momentum relativo)
BENCHMARK = {"US": "^GSPC", "KR": "^KS11", "JP": "^N225", "HK": "^HSI", "CN": "000001.SS", "EU": "^STOXX50E"}


# Bolsas que cotam em subunidades: o preço vem em pence/cêntimos, as contas e a market cap do Yahoo na unidade
# principal. Sem normalizar, DCF e Altman erravam 100× (AZN.L: DCF 136,97 "−99%" em vez de 13 697p).
MINOR_UNITS = {"GBp": ("GBP", 100.0), "GBX": ("GBP", 100.0), "ZAc": ("ZAR", 100.0), "ZAC": ("ZAR", 100.0),
               "ILA": ("ILS", 100.0)}


def major_currency(currency: str | None) -> tuple[str | None, float]:
    """(moeda principal, n.º de subunidades por unidade): 'GBp' → ('GBP', 100); 'USD' → ('USD', 1)."""
    if not currency:
        return None, 1.0
    if currency in MINOR_UNITS:
        return MINOR_UNITS[currency]
    return currency.upper(), 1.0


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
