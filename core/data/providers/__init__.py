from .base import Provider
from .keyed import FMP, AkShare, Alpaca, AlphaVantage, EODHD, Finnhub, ITick, Marketstack, Tiingo, TwelveData
from .yfinance_p import YFinance

ALL = [YFinance, FMP, Finnhub, Alpaca, Tiingo, ITick, EODHD, TwelveData, AlphaVantage, Marketstack, AkShare]


def default_providers() -> dict[str, Provider]:
    return {cls.name: cls() for cls in ALL}
