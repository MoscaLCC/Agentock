from pydantic import BaseModel, Field


class Player(BaseModel):
    name: str
    symbol: str | None = None
    share_pct: float | None = Field(default=None, description="quota de mercado em %, se houver fonte")
    year: int | None = None
    source: str | None = None


class MarketStructure(BaseModel):
    industry: str
    market_definition: str = Field(description="que mercado se mede (ex.: smartphones a nível mundial, por unidades)")
    market_size: str | None = Field(default=None, description="dimensão com unidade, ano e fonte, se houver")
    structure: str = Field(description="monopólio | duopólio | oligopólio | concorrencial | fragmentado")
    concentration: str = Field(description="ex.: 'top-3 com ~70%'; HHI se calculável")
    players: list[Player] = Field(description="principais players com quota e fonte")
    trends: list[str] = Field(description="2-4 tendências de quota (quem ganha/perde)")
    moat_notes: list[str] = Field(description="barreiras à entrada / vantagens competitivas observadas")
    sources: list[str]
