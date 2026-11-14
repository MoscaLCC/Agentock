from pydantic import BaseModel, Field


class SourceSentiment(BaseModel):
    score: float | None = Field(default=None, ge=-1, le=1)
    basis: str = Field(description="em que se baseia (ex.: '9 notícias, 6 positivas, 2 negativas')")


class SentimentView(BaseModel):
    overall_score: float = Field(ge=-1, le=1, description="-1 muito negativo … +1 muito positivo")
    label: str = Field(description="muito negativo | negativo | neutro | positivo | muito positivo")
    trend: str = Field(description="a melhorar | estável | a piorar (janelas curtas vs longas)")
    news: SourceSentiment
    analysts: SourceSentiment
    insiders: SourceSentiment
    drivers: list[str] = Field(description="2-4 fatores que explicam o sentimento, com números")
    score: int = Field(ge=-2, le=2, description="o mesmo sentimento na escala −2…+2")
    summary: str = Field(description="2 frases em português de Portugal")
