"""Deteção de alteração de estado — regras determinísticas (sem LLM).

- Salto >= immediate_delta níveis  -> confirma e alerta de imediato.
- Mudança de 1 nível               -> só confirma após confirm_runs execuções consecutivas
                                      com a mesma nova classificação (histerese).
"""
from dataclasses import dataclass

from .ratings import Rating


@dataclass
class ChangeRules:
    immediate_delta: int = 2
    confirm_runs: int = 2


@dataclass
class Change:
    ticker: str
    old: Rating
    new: Rating
    kind: str  # "immediate" | "confirmed"

    @property
    def delta(self) -> int:
        return int(self.new) - int(self.old)


def evaluate(conn, ticker: str, new: Rating, rules: ChangeRules | None = None, ts: str = "") -> Change | None:
    from .db import now
    rules = rules or ChangeRules()
    ts = ts or now()
    row = conn.execute("SELECT * FROM state WHERE ticker=?", (ticker,)).fetchone()

    if row is None:  # primeira observação: define a base, sem alerta
        conn.execute("INSERT INTO state(ticker, confirmed, confirmed_ts) VALUES (?,?,?)", (ticker, int(new), ts))
        conn.commit()
        return None

    old = Rating(row["confirmed"])
    if new == old:
        conn.execute("UPDATE state SET pending=NULL, pending_count=0 WHERE ticker=?", (ticker,))
        conn.commit()
        return None

    if abs(int(new) - int(old)) >= rules.immediate_delta:
        kind = "immediate"
    else:
        count = row["pending_count"] + 1 if row["pending"] == int(new) else 1
        if count < rules.confirm_runs:
            conn.execute("UPDATE state SET pending=?, pending_count=? WHERE ticker=?", (int(new), count, ticker))
            conn.commit()
            return None
        kind = "confirmed"

    conn.execute(
        "UPDATE state SET confirmed=?, confirmed_ts=?, pending=NULL, pending_count=0 WHERE ticker=?",
        (int(new), ts, ticker),
    )
    conn.commit()
    return Change(ticker, old, new, kind)
