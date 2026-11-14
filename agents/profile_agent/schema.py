from pydantic import BaseModel, Field


class CrossListing(BaseModel):
    symbol: str
    exchange: str | None = None
    market: str
    name: str | None = None


class Profile(BaseModel):
    query: str
    symbol: str
    resolution_note: str | None = Field(default=None, description="como o pedido foi resolvido, se diferente do escrito "
                                                                  "(ex.: 'SSU → Samsung Electronics (005930.KS)')")
    name: str
    market: str
    exchange: str | None = None
    calendar: str | None = Field(default=None, description="código exchange_calendars da bolsa principal")
    currency: str | None = None
    sector: str | None = None
    industry: str | None = None
    country: str | None = None
    summary: str | None = None
    price: float | None = None
    change_pct: float | None = None
    quote_ts: str | None = None
    market_cap: float | None = None
    market_cap_usd: float | None = None
    first_trade_date: str | None = None
    days_listed: int | None = None
    ipo_recente: bool = False
    history_days: int = 0
    shares_outstanding: float | None = None
    float_shares: float | None = None
    benchmark: str | None = None
    cross_listings: list[CrossListing] = Field(default_factory=list)
    peers_hint: list[str] = Field(default_factory=list)
    sources: dict = Field(default_factory=dict)
