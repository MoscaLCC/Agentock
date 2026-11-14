"""Memória e alerta de classificações de IPO (mensagem compacta: core/messages.py)."""
from core import db, messages
from core.notify import default_notifier
from core.ratings import IpoRating
from core.schemas import IpoSynthesis
from core.util import as_dict


def run(synthesis, ipo=None, run_id=None, notify=True, conn=None):
    s = synthesis if isinstance(synthesis, IpoSynthesis) else IpoSynthesis.model_validate(as_dict(synthesis))
    cal = as_dict(ipo) or {}  # entrada do calendário: completa o que a análise não trouxe
    fill = {k: cal.get(src) for k, src in (("symbol", "symbol"), ("exchange", "exchange"), ("ipo_date", "date"))
            if not getattr(s, k) and cal.get(src)}
    if fill:
        s = IpoSynthesis.model_validate({**s.model_dump(mode="json"), **fill})
    conn = conn or db.connect()
    rating = IpoRating.parse(s.rating)
    row = conn.execute("SELECT rating FROM ipo_ratings WHERE name=? ORDER BY id DESC LIMIT 1", (s.name,)).fetchone()
    prev = IpoRating(row["rating"]) if row else None
    saved = db.save_ipo_rating(conn, name=s.name, symbol=s.symbol, exchange=s.exchange, ipo_date=s.ipo_date,
                               rating=rating, confidence=s.confidence, price_range=s.deal.price_range,
                               payload=s.model_dump(mode="json"), run_id=run_id)
    cmd = f"/ipo_{messages.command_arg(s.symbol)}" if s.symbol else f"/ipo_{saved}"
    sent = None
    # atenção: IpoRating.NEUTRO == 0 é "falsy" — comparar sempre com `is None`
    if notify and (prev is None or prev != rating):
        sent = default_notifier().send(messages.ipo_rating(s, rating, prev, cmd), html=True)
    return {"saved_id": saved, "rating": rating.label, "previous": prev.label if prev is not None else None,
            "sent": sent, "command": cmd}
