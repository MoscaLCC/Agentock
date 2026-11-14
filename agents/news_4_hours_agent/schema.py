from pydantic import BaseModel, Field


class NewsItem(BaseModel):
    title: str
    source: str
    url: str
    published_at: str = Field(description="ISO 8601 UTC")
    summary: str = Field(description="1-2 frases")
    category: str = Field(description="earnings | analyst | regulatory | product | macro | m&a | other")
    relevance: int = Field(ge=1, le=5, description="1=marginal, 5=move o preço")


class NewsReport(BaseModel):
    ticker: str
    company: str
    searched_at: str
    window_hours: int
    items: list[NewsItem]
