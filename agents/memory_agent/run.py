from core import db
from core.ratings import Rating
from core.schemas import Synthesis
from core.util import as_dict


def run(synthesis, conn=None):
    s = synthesis if isinstance(synthesis, Synthesis) else Synthesis.model_validate(as_dict(synthesis))
    conn = conn or db.connect()
    run_id = db.save_run(
        conn, ticker=s.ticker, rating=Rating.parse(s.rating), confidence=s.confidence, price=s.price,
        reasons=s.reasons, payload={**s.payload, "risks": s.risks, "warnings": s.warnings, "data_gaps": s.data_gaps,
                                    "horizon": s.horizon},
        version=s.version, market=s.market, currency=s.currency, run_id=s.run_id,
    )
    return {"saved_id": run_id, "ticker": s.ticker, "rating": s.rating, "version": s.version}
