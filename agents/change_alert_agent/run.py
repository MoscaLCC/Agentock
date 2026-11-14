from core import db
from core.changes import ChangeRules, evaluate
from core.notify import default_notifier, format_change
from core.ratings import Rating
from core.schemas import Synthesis


def run(synthesis: Synthesis, conn=None, notifier=None, rules: ChangeRules | None = None) -> dict:
    conn = conn or db.connect()
    change = evaluate(conn, synthesis.ticker, Rating.parse(synthesis.rating), rules)
    if change is None:
        return {"changed": False}

    msg = format_change(change, synthesis.price, synthesis.confidence, synthesis.reasons)
    try:
        sent = (notifier or default_notifier()).send(msg)
    except Exception as e:  # falha de rede não pode perder o registo da alteração
        sent, msg = False, f"{msg}\n[ERRO ao notificar: {e}]"
    conn.execute(
        "INSERT INTO alerts(ticker, ts, old_rating, new_rating, kind, message, sent) VALUES (?,?,?,?,?,?,?)",
        (change.ticker, db.now(), int(change.old), int(change.new), change.kind, msg, int(sent)),
    )
    conn.commit()
    return {"changed": True, "kind": change.kind, "old": change.old.label,
            "new": change.new.label, "sent": sent}
