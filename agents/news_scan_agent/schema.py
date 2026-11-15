from pydantic import BaseModel, Field

CATEGORY = "earnings | analyst | regulatory | product | macro | m&a | legal | management | other"


class Annotation(BaseModel):
    id: str = Field(description="o id do item da recolha, copiado tal e qual (ex.: 'n3fa91c')")
    relevance: int = Field(ge=1, le=5, description="1=marginal, 5=move o preço")
    tone: str = Field(description="positivo | negativo | neutro (efeito provável no preço da ação)")
    category: str = Field(description=CATEGORY)
    summary: str = Field(description="1-2 frases em português de Portugal, com os números do item")


class WebItem(BaseModel):
    title: str = Field(description="título no original")
    source: str
    url: str
    published_at: str = Field(description="ISO 8601 UTC")
    time_confirmed: bool = Field(description="true só se abriste a página e leste a data/hora de publicação")
    relevance: int = Field(ge=1, le=5)
    tone: str = Field(description="positivo | negativo | neutro")
    category: str = Field(description=CATEGORY)
    summary: str = Field(description="1-2 frases em português de Portugal")


class NewsScan(BaseModel):
    scanned_at: str = Field(description="a hora 'Agora' da tarefa, copiada tal e qual, em ISO 8601 UTC")
    annotations: list[Annotation] = Field(description="um por item relevante da recolha; os irrelevantes ficam de fora")
    web_items: list[WebItem] = Field(default_factory=list, description="só notícias que NÃO estão na recolha")
