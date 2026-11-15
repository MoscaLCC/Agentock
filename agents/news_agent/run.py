"""2.1 — junta recolha + triagem e serve as 4 janelas (core/news.py). Corre sempre: é só código."""
from datetime import datetime, timezone

from core import news
from core.util import as_dict


def run(profile, feed=None, scan=None):
    p, feed, scan = as_dict(profile), as_dict(feed), as_dict(scan)
    if feed is None and scan is None:
        raise ValueError("sem recolha das APIs nem triagem: notícias indisponíveis")
    return news.merge(feed, scan, datetime.now(timezone.utc), symbol=p["symbol"], company=p.get("name") or "")
