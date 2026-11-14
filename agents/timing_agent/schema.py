from pydantic import BaseModel, Field


class TimingView(BaseModel):
    entry_quality: str = Field(description="boa | neutra | má | esperar")
    score: int = Field(ge=-2, le=2)
    rationale: list[str] = Field(description="2-4 razões com números dos dados")
    buy_zone_low: float | None = None
    buy_zone_high: float | None = None
    stop_reference: float | None = Field(default=None, description="referência de invalidação (ex.: suporte ou 2 ATR)")
    wait_conditions: list[str] = Field(default_factory=list, description="o que esperar antes de entrar, se for o caso")
    next_session_bias: str | None = Field(default=None, description="positivo | negativo | neutro (sinais das sessões que lideram)")
    summary: str
