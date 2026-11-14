from pydantic import BaseModel, Field


class TechnicalView(BaseModel):
    trend: str = Field(description="alta | baixa | lateral | indefinida")
    momentum: str = Field(description="forte | positivo | neutro | negativo | fraco")
    signals: list[str] = Field(description="sinais concretos, cada um com o número que o suporta")
    supports: list[float] = Field(default_factory=list)
    resistances: list[float] = Field(default_factory=list)
    score: int = Field(ge=-2, le=2, description="-2 muito negativo … +2 muito positivo")
    summary: str = Field(description="2-3 frases em português de Portugal")
    caveats: list[str] = Field(default_factory=list, description="limitações (pouco histórico, limites diários, etc.)")
