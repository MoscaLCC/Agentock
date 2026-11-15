"""2.1a — recolha única de notícias (core/news.py). O LLM já não chama a API: recebe esta lista no prompt."""
from datetime import datetime, timezone

from core import news
from core.data import DataUnavailable, get_router
from core.util import as_dict


def run(profile):
    p = as_dict(profile)
    now = datetime.now(timezone.utc)
    try:
        res = get_router().get("news", p["symbol"])
        raw, provider = res.data, res.provider
    except DataUnavailable as e:
        raw, provider = [], f"indisponível: {e}"
    out = news.collect(raw, now, symbol=p["symbol"], company=p.get("name") or "")
    out["provider"] = provider
    return out
