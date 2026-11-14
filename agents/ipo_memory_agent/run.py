"""Memória e alerta de classificações de IPO."""
from core import db
from core.notify import DISCLAIMER, default_notifier
from core.ratings import IpoRating
from core.schemas import IpoSynthesis
from core.util import as_dict


def message(s: IpoSynthesis, rating: IpoRating, prev: IpoRating | None) -> str:
    head = f"IPO {s.name} ({s.symbol or '—'}, {s.exchange or '—'}, {s.ipo_date or 'data por confirmar'}): {rating.label}"
    if prev is not None and prev != rating:
        head += f" (antes: {prev.label})"
    lines = [head, f"Confiança: {s.confidence:.0%}", f"Preço indicativo: {s.deal.price_range or 'não divulgado'}"]
    if s.deal.implied_valuation_low:
        lines.append(f"Valorização implícita: {s.deal.implied_valuation_low / 1e9:,.1f}–"
                     f"{(s.deal.implied_valuation_high or s.deal.implied_valuation_low) / 1e9:,.1f} mil M {s.deal.currency or ''}")
    lines.append("A favor: " + "; ".join(s.bull_case[:2]))
    lines.append("Contra: " + "; ".join(s.bear_case[:2]))
    if s.not_disclosed:
        lines.append("Ainda não divulgado: " + ", ".join(s.not_disclosed[:6]))
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def run(synthesis, ipo=None, run_id=None, notify=True, conn=None):
    s = synthesis if isinstance(synthesis, IpoSynthesis) else IpoSynthesis.model_validate(as_dict(synthesis))
    conn = conn or db.connect()
    rating = IpoRating.parse(s.rating)
    row = conn.execute("SELECT rating FROM ipo_ratings WHERE name=? ORDER BY id DESC LIMIT 1", (s.name,)).fetchone()
    prev = IpoRating(row["rating"]) if row else None
    saved = db.save_ipo_rating(conn, name=s.name, symbol=s.symbol, exchange=s.exchange, ipo_date=s.ipo_date,
                               rating=rating, confidence=s.confidence, price_range=s.deal.price_range,
                               payload=s.model_dump(mode="json"), run_id=run_id)
    sent = None
    if notify and (prev is None or prev != rating):
        sent = default_notifier().send(message(s, rating, prev))
    # atenção: IpoRating.NEUTRO == 0 é "falsy" — comparar sempre com `is None`
    return {"saved_id": saved, "rating": rating.label, "previous": prev.label if prev is not None else None,
            "sent": sent}
