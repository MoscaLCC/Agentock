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
    min_gap_hours: float = 4.0   # a confirmação tem de vir de uma análise feita pelo menos N horas depois


@dataclass
class Change:
    ticker: str
    old: Rating
    new: Rating
    kind: str  # "immediate" | "confirmed"

    @property
    def delta(self) -> int:
        return int(self.new) - int(self.old)


def _hours_between(a: str | None, b: str) -> float:
    from datetime import datetime
    if not a:
        return 1e9
    return abs((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds()) / 3600


def evaluate(conn, ticker: str, new: Rating, rules: ChangeRules | None = None, ts: str = "",
             run_id: str | None = None) -> Change | None:
    """run_id: a mesma análise avaliada duas vezes (retry, retoma) não conta como segunda observação."""
    from .db import now
    rules = rules or ChangeRules()
    ts = ts or now()
    row = conn.execute("SELECT * FROM state WHERE ticker=?", (ticker,)).fetchone()
    if row is not None and run_id and row["last_run_id"] == run_id:
        return None

    if row is None:  # primeira observação: define a base, sem alerta
        conn.execute("INSERT INTO state(ticker, confirmed, confirmed_ts, last_run_id) VALUES (?,?,?,?)",
                     (ticker, int(new), ts, run_id))
        conn.commit()
        return None

    old = Rating(row["confirmed"])
    if new == old:
        conn.execute("UPDATE state SET pending=NULL, pending_count=0, pending_ts=NULL, last_run_id=? WHERE ticker=?",
                     (run_id, ticker))
        conn.commit()
        return None

    if abs(int(new) - int(old)) >= rules.immediate_delta:
        kind = "immediate"
    else:
        same = row["pending"] == int(new)
        if same and _hours_between(row["pending_ts"], ts) < rules.min_gap_hours:
            # a mesma classificação vista outra vez pouco depois (reanálise, cache): não é uma confirmação nova
            conn.execute("UPDATE state SET last_run_id=? WHERE ticker=?", (run_id, ticker))
            conn.commit()
            return None
        count = row["pending_count"] + 1 if same else 1
        if count < rules.confirm_runs:
            conn.execute("UPDATE state SET pending=?, pending_count=?, pending_ts=?, last_run_id=? WHERE ticker=?",
                         (int(new), count, ts, run_id, ticker))
            conn.commit()
            return None
        kind = "confirmed"

    conn.execute(
        "UPDATE state SET confirmed=?, confirmed_ts=?, pending=NULL, pending_count=0, pending_ts=NULL, last_run_id=?"
        " WHERE ticker=?",
        (int(new), ts, run_id, ticker),
    )
    conn.commit()
    return Change(ticker, old, new, kind)
