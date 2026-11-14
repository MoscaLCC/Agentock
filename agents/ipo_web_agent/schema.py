from pydantic import BaseModel, Field


class WebIpo(BaseModel):
    date: str | None = Field(default=None, description="data prevista de estreia (YYYY-MM-DD) se conhecida")
    name: str
    symbol: str | None = None
    exchange: str
    market: str = Field(description="HK | CN | KR | JP | EU")
    price_range: str | None = None
    currency: str | None = Field(default=None, description="moeda do intervalo de preço (ex.: JPY, HKD)")
    value_usd: float | None = Field(default=None, description="dimensão da oferta em USD, se divulgada")
    source: str


class IpoWebList(BaseModel):
    ipos: list[WebIpo]
    notes: str | None = None
