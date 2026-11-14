from pydantic import BaseModel, Field


class Peer(BaseModel):
    symbol: str = Field(description="símbolo yfinance validado com mcp__market__profile")
    name: str
    market: str | None = None
    overlap: str = Field(description="alta | média | baixa — sobreposição de negócio")
    reason: str = Field(description="em que segmento concorrem")


class CompetitorList(BaseModel):
    peers: list[Peer] = Field(description="5-8 concorrentes cotados diretos")
    unlisted: list[str] = Field(default_factory=list, description="concorrentes relevantes não cotados")
    rejected_hints: list[str] = Field(default_factory=list, description="pistas do FMP rejeitadas e porquê")
    notes: str | None = None
