from pydantic import BaseModel, Field


class FundamentalView(BaseModel):
    valuation: str = Field(description="barata | justa | cara | indeterminada")
    quality: str = Field(description="alta | média | baixa")
    growth: str = Field(description="forte | moderado | fraco | negativo")
    balance_sheet_risk: str = Field(description="baixo | médio | alto")
    score: int = Field(ge=-2, le=2)
    key_points: list[str] = Field(description="3-5 pontos, cada um com o número que o suporta")
    risks: list[str] = Field(description="1-3 riscos fundamentais")
    summary: str = Field(description="2-3 frases em português de Portugal")
