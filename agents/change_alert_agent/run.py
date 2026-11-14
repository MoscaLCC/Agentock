import json
from difflib import SequenceMatcher

from core import db, messages
from core.changes import ChangeRules, evaluate
from core.notify import default_notifier
from core.ratings import Rating
from core.schemas import Synthesis
from core.util import as_dict


def reasons_diff(old: list[str], new: list[str], threshold: float = 0.6) -> dict:
    """Pontos novos e pontos que deixaram de constar (comparação aproximada de texto)."""
    def present(r, pool):
        return any(SequenceMatcher(None, r.lower(), o.lower()).ratio() >= threshold for o in pool)
    return {"added": [r for r in new if not present(r, old)], "removed": [r for r in old if not present(r, new)]}


def previous_points(conn, ticker: str) -> list[str]:
    """Pontos curtos da classificação anterior (ou as razões, em registos antigos sem versão curta)."""
    rows = conn.execute("SELECT reasons, payload FROM runs WHERE ticker=? ORDER BY id DESC LIMIT 2", (ticker,)).fetchall()
    if len(rows) < 2:
        return []
    payload = json.loads(rows[1]["payload"] or "{}")
    return payload.get("key_points") or json.loads(rows[1]["reasons"] or "[]")


def previous_reasons(conn, ticker: str) -> list[str]:
    rows = conn.execute("SELECT reasons FROM runs WHERE ticker=? ORDER BY id DESC LIMIT 2", (ticker,)).fetchall()
    return json.loads(rows[1]["reasons"]) if len(rows) > 1 and rows[1]["reasons"] else []


def run(synthesis, conn=None, notifier=None, rules: ChangeRules | None = None) -> dict:
    s = synthesis if isinstance(synthesis, Synthesis) else Synthesis.model_validate(as_dict(synthesis))
    conn = conn or db.connect()
    change = evaluate(conn, s.ticker, Rating.parse(s.rating), rules)
    if change is None:
        return {"changed": False}

    current = s.key_points or [messages.first_clause(r) for r in s.reasons]
    previous = [messages.first_clause(p) for p in previous_points(conn, s.ticker)]
    diff = reasons_diff(previous, current)
    msg = messages.rating_change(change, s, diff)
    try:
        sent = (notifier or default_notifier()).send(msg, html=True)
    except Exception as e:  # falha de rede não pode perder o registo da alteração
        sent, msg = False, f"{msg}\n[ERRO ao notificar: {e}]"
    conn.execute(
        "INSERT INTO alerts(ticker, ts, old_rating, new_rating, kind, message, sent) VALUES (?,?,?,?,?,?,?)",
        (change.ticker, db.now(), int(change.old), int(change.new), change.kind, msg, int(sent)),
    )
    conn.commit()
    return {"changed": True, "kind": change.kind, "old": change.old.label,
            "new": change.new.label, "sent": sent, "diff": diff}
