"""2.10 — sentimento por código (core/sentiment.py). Social (redes) não está nas fontes: não entra."""
from core import sentiment
from core.util import as_dict


def run(profile, news=None, analysts=None, insiders=None):
    out = sentiment.compute(as_dict(news), as_dict(analysts), as_dict(insiders))
    out["symbol"] = as_dict(profile)["symbol"]
    return out
