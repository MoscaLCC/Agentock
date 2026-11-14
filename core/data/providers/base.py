"""Base dos fornecedores e formatos normalizados.

Formatos (todos os fornecedores devolvem isto):
  quote         {price, prev_close, change_pct, currency, ts}
  eod/intraday  [{t, o, h, l, c, v}]  (t: 'YYYY-MM-DD' no EOD; ISO UTC no intraday), ordem cronológica
  profile       {name, exchange, currency, sector, industry, country, market_cap}
  news          [{title, url, source, published_at (ISO UTC), summary}]
  analyst_recs  {period, strong_buy, buy, hold, sell, strong_sell}
  price_targets {current, low, high, mean, median}
  upgrades      [{date, firm, from_grade, to_grade, action, price_target, prior_price_target}]
  peers         [symbol]
  calendar      {earnings_dates, ex_dividend, dividend_date, eps_estimate_avg, revenue_estimate_avg}
  search        [{symbol, exchange, name, type}]
  fx            {pair, rate, ts}
  ipo_calendar  [{date, symbol, name, exchange, price_range, shares, value, status}]
Um resultado vazio (None, [] ou {}) faz o router passar ao fornecedor seguinte.
"""
import math
import os
from datetime import date, datetime, timedelta, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def unix_to_iso(ts: float, ms: bool = False) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(ts / 1000 if ms else ts, timezone.utc).isoformat(timespec="seconds")


def num(x):
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def pct(price, prev):
    return (price / prev - 1) * 100 if price and prev else None


def bars_from_records(rows, t_key, o="open", h="high", l="low", c="close", v="volume", daily=True) -> list[dict]:
    out = []
    for r in rows:
        t = r.get(t_key)
        if t is None:
            continue
        t = str(t)[:10] if daily else str(t)
        out.append({"t": t, "o": num(r.get(o)), "h": num(r.get(h)), "l": num(r.get(l)),
                    "c": num(r.get(c)), "v": num(r.get(v))})
    return sorted(out, key=lambda b: b["t"])


def bars_from_df(df, daily: bool) -> list[dict]:
    if df is None or df.empty:
        return []
    out = []
    for idx, row in df.iterrows():
        if daily:
            t = idx.date().isoformat()
        else:
            t = (idx.tz_convert("UTC") if idx.tzinfo else idx).isoformat()
        out.append({"t": t, "o": num(row.get("Open")), "h": num(row.get("High")), "l": num(row.get("Low")),
                    "c": num(row.get("Close")), "v": num(row.get("Volume"))})
    return out


class Provider:
    name = ""
    env: tuple[str, ...] = ()
    capabilities: frozenset[str] = frozenset()
    weights: dict[str, int] = {}

    def configured(self) -> bool:
        return all(os.environ.get(e) for e in self.env)

    def key(self, i: int = 0) -> str:
        return os.environ[self.env[i]]

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities

    def weight(self, capability: str) -> int:
        return self.weights.get(capability, 1)

    def call(self, capability: str, symbol, **params):
        return getattr(self, capability)(symbol, **params)
