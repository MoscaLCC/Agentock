"""Contratos partilhados entre agentes."""
from pydantic import BaseModel, Field


class Synthesis(BaseModel):
    """Output do agente de síntese (2.15 + 2.18 + 2.19) — input da memória e do detetor."""
    ticker: str
    rating: str = Field(description="strong_sell | sell | hold | buy | strong_buy")
    confidence: float = Field(ge=0, le=1)
    price: float | None = None
    reasons: list[str] = Field(default_factory=list, description="2-5 razões principais")
    payload: dict = Field(default_factory=dict, description="JSONs completos das análises")
