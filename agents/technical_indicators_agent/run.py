"""2.8a — indicadores técnicos. Funções puras em `compute()` (testáveis sem rede)."""
import math

import pandas as pd

from core.data import get_router
from core.util import as_dict, r2


def daily_limit_pct(symbol: str) -> float | None:
    """Limite diário de variação: China ±10% (±20% STAR 688 / ChiNext 300-301), Coreia ±30%."""
    code, _, sfx = symbol.partition(".")
    if sfx in ("SS", "SZ"):
        return 20.0 if code.startswith(("688", "300", "301")) else 10.0
    if sfx in ("KS", "KQ"):
        return 30.0
    return None


def pivots(df: pd.DataFrame, window: int = 5, lookback: int = 120, tol: float = 0.015):
    d = df.tail(lookback)
    highs, lows = [], []
    for i in range(window, len(d) - window):
        h, l = d["h"].iloc[i - window:i + window + 1], d["l"].iloc[i - window:i + window + 1]
        if d["h"].iloc[i] == h.max():
            highs.append(float(d["h"].iloc[i]))
        if d["l"].iloc[i] == l.min():
            lows.append(float(d["l"].iloc[i]))

    def cluster(levels):
        out = []
        for lv in sorted(levels):
            if out and abs(lv / out[-1][-1] - 1) < tol:
                out[-1].append(lv)
            else:
                out.append([lv])
        return [sum(c) / len(c) for c in out]

    return cluster(lows), cluster(highs)


def compute(bars: list[dict], symbol: str = "") -> dict:
    import pandas_ta_classic as ta

    df = pd.DataFrame(bars).dropna(subset=["c"])
    if df.empty:
        return {"available": False, "limitations": ["sem preços"]}
    df.index = pd.to_datetime(df["t"])
    c, n = df["c"], len(df)
    last = float(c.iloc[-1])
    lim = []

    def tail(series):
        return None if series is None or series.dropna().empty else float(series.dropna().iloc[-1])

    sma = {L: tail(ta.sma(c, length=L)) if n >= L else None for L in (20, 50, 200)}
    for L, v in sma.items():
        if v is None:
            lim.append(f"sem SMA{L}: só {n} sessões")
    rsi = tail(ta.rsi(c, length=14)) if n > 15 else None
    macd_df = ta.macd(c) if n > 35 else None
    macd = None
    if macd_df is not None and not macd_df.dropna().empty:
        row = macd_df.dropna().iloc[-1]
        macd = {"macd": r2(row.iloc[0], 4), "hist": r2(row.iloc[1], 4), "signal": r2(row.iloc[2], 4)}
    atr = tail(ta.atr(df["h"], df["l"], c, length=14)) if n > 15 else None

    bb = None
    if n >= 20:
        mid, sd = c.rolling(20).mean().iloc[-1], c.rolling(20).std(ddof=0).iloc[-1]  # Bollinger: populacional
        up, lo = mid + 2 * sd, mid - 2 * sd
        bb = {"upper": r2(up), "mid": r2(mid), "lower": r2(lo), "pct_b": r2((last - lo) / (up - lo) if up != lo else None),
              "width_pct": r2((up - lo) / mid * 100 if mid else None)}

    def ret(days):
        return r2((last / float(c.iloc[-days - 1]) - 1) * 100) if n > days else None

    win = c.tail(252)
    hi52, lo52 = float(df["h"].tail(252).max()), float(df["l"].tail(252).min())
    vol = df["v"].fillna(0)
    avg20 = float(vol.tail(20).mean()) if n >= 20 else None

    cross = None
    if n >= 220:
        s50, s200 = ta.sma(c, length=50), ta.sma(c, length=200)
        diff = (s50 - s200).dropna().tail(21)
        if len(diff) > 1 and (diff.iloc[0] < 0) != (diff.iloc[-1] < 0):
            cross = "golden" if diff.iloc[-1] > 0 else "death"

    above50 = sma[50] is not None and last > sma[50]
    above200 = sma[200] is not None and last > sma[200]
    if sma[50] and sma[200]:
        label = "alta" if above50 and above200 and sma[50] > sma[200] else \
                "baixa" if not above50 and not above200 and sma[50] < sma[200] else "lateral"
    elif sma[50]:
        label = "alta" if above50 else "baixa"
    else:
        label = "indefinida"

    supports, resistances = pivots(df) if n > 15 else ([], [])
    supports = [r2(x) for x in sorted([x for x in supports if x < last], reverse=True)[:3]]
    resistances = [r2(x) for x in sorted([x for x in resistances if x > last])[:3]]

    limit = daily_limit_pct(symbol)
    today_chg = (last / float(c.iloc[-2]) - 1) * 100 if n > 1 else None
    price_limit = None
    if limit:
        price_limit = {"limit_pct": limit, "today_change_pct": r2(today_chg),
                       "near_limit": bool(today_chg is not None and abs(today_chg) >= 0.8 * limit)}

    vol_ann = None
    if n > 30:
        lr = (c / c.shift(1)).apply(lambda x: math.log(x) if x and x > 0 else None).dropna().tail(252)
        vol_ann = r2(float(lr.std()) * math.sqrt(252) * 100)

    return {
        "available": True, "bars": n, "last_date": str(df.index[-1].date()), "close": r2(last, 4),
        "sma20": r2(sma[20]), "sma50": r2(sma[50]), "sma200": r2(sma[200]), "ema20": r2(tail(ta.ema(c, length=20))) if n >= 20 else None,
        "rsi14": r2(rsi), "macd": macd, "atr14": r2(atr), "atr_pct": r2(atr / last * 100) if atr else None, "bollinger": bb,
        "volume": {"last": r2(float(vol.iloc[-1]), 0), "avg20": r2(avg20, 0),
                   "rel": r2(float(vol.iloc[-1]) / avg20) if avg20 else None},
        "returns_pct": {"1w": ret(5), "1m": ret(21), "3m": ret(63), "6m": ret(126), "1y": ret(252)},
        "volatility_ann_pct": vol_ann,
        "high_52w": r2(hi52), "low_52w": r2(lo52), "dist_high_52w_pct": r2((last / hi52 - 1) * 100),
        "dist_low_52w_pct": r2((last / lo52 - 1) * 100),
        "trend": {"label": label, "above_sma50": above50, "above_sma200": above200, "cross_last_20d": cross},
        "levels": {"supports": supports, "resistances": resistances},
        "atr_zones": {"stop_2atr": r2(last - 2 * atr) if atr else None, "target_2atr": r2(last + 2 * atr) if atr else None},
        "price_limit": price_limit, "limitations": lim, "window_days": len(win),
    }


def run(profile):
    p = as_dict(profile)
    res = get_router().get("eod", p["symbol"], days=420)
    out = compute(res.data, p["symbol"])
    out.update({"symbol": p["symbol"], "currency": p.get("currency"), "provider": res.provider})
    return out
