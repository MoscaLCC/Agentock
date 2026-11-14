"""Mercado de um símbolo (formato yfinance) e calendário de bolsa correspondente."""

SUFFIX_MARKET = {
    ".KS": "KR", ".KQ": "KR",
    ".T": "JP",
    ".HK": "HK",
    ".SS": "CN", ".SZ": "CN",
    ".L": "EU", ".DE": "EU", ".F": "EU", ".AS": "EU", ".PA": "EU", ".SW": "EU", ".MI": "EU",
    ".MC": "EU", ".BR": "EU", ".LS": "EU", ".ST": "EU", ".CO": "EU", ".HE": "EU", ".OL": "EU",
    ".VI": "EU", ".IR": "EU", ".IL": "EU",
}

# exchange_calendars (verificado na Fase 0; Shenzhen usa XSHG)
SUFFIX_CALENDAR = {
    ".KS": "XKRX", ".KQ": "XKRX", ".T": "XTKS", ".HK": "XHKG", ".SS": "XSHG", ".SZ": "XSHG",
    ".L": "XLON", ".IL": "XLON", ".DE": "XETR", ".F": "XFRA", ".AS": "XAMS", ".PA": "XPAR",
    ".SW": "XSWX", ".MI": "XMIL", ".MC": "XMAD", ".BR": "XBRU", ".LS": "XLIS", ".ST": "XSTO",
    ".CO": "XCSE", ".HE": "XHEL", ".OL": "XOSL", ".VI": "XWBO", ".IR": "XDUB",
}

MARKETS = ("US", "EU", "JP", "HK", "CN", "KR")


def suffix(symbol: str) -> str:
    i = symbol.rfind(".")
    return symbol[i:].upper() if i > 0 else ""


def market_of(symbol: str | None) -> str:
    if not symbol:
        return "GLOBAL"
    if symbol.startswith("^"):
        return "INDEX"
    if symbol.endswith("=F"):
        return "FUT"
    if symbol.endswith("=X"):
        return "FX"
    sfx = suffix(symbol)
    if not sfx:
        return "US"
    return SUFFIX_MARKET.get(sfx, "OTHER")


def calendar_code(symbol: str) -> str | None:
    if market_of(symbol) == "US":
        return "XNYS"
    return SUFFIX_CALENDAR.get(suffix(symbol))


def base_code(symbol: str) -> str:
    """'0700.HK' -> '0700'; 'AAPL' -> 'AAPL'."""
    sfx = suffix(symbol)
    return symbol[: -len(sfx)] if sfx else symbol
