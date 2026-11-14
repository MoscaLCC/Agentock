from core import db
from core.ratings import Rating
from core.schemas import Synthesis


def run(synthesis: Synthesis, conn=None) -> int:
    conn = conn or db.connect()
    return db.save_run(
        conn, ticker=synthesis.ticker, rating=Rating.parse(synthesis.rating),
        confidence=synthesis.confidence, price=synthesis.price,
        reasons=synthesis.reasons, payload=synthesis.payload,
    )
