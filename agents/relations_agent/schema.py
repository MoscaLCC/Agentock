from pydantic import BaseModel, Field


class Related(BaseModel):
    name: str
    relation: str = Field(description="mãe | subsidiária | joint venture | parceiro | fornecedor | cliente | participada")
    symbol: str | None = Field(default=None, description="símbolo yfinance se for cotada")
    stake_pct: float | None = None
    country: str | None = None
    importance: str = Field(description="alta | média | baixa (para o negócio da empresa)")
    note: str | None = None
    recent_change_pct: float | None = Field(default=None, description="variação do dia (mcp__market__quote), se cotada")


class Relations(BaseModel):
    parent: Related | None = None
    related: list[Related] = Field(description="subsidiárias relevantes, parceiros, fornecedores e clientes-chave")
    subsidiaries_count: int | None = Field(default=None, description="nº de subsidiárias no documento oficial")
    summary: str = Field(description="2-3 frases: dependências e exposição relevantes")
    sources: list[str]
