"""Contratos partilhados entre agentes."""
import re

from pydantic import BaseModel, Field, field_validator

SHORT = "versão curta para o telemóvel"


class Synthesis(BaseModel):
    """Classificação final de uma ação (saída do guard) — input da memória e do detetor de alterações."""
    ticker: str
    rating: str = Field(description="strong_sell | sell | hold | buy | strong_buy")
    confidence: float = Field(ge=0, le=1)
    price: float | None = None
    currency: str | None = None
    market: str | None = None
    version: str = "v1"
    horizon: str | None = Field(default=None, description="horizonte da tese, ex.: '3-12 meses'")
    headline: str | None = Field(default=None, description=f"{SHORT}: 1 frase")
    key_points: list[str] = Field(default_factory=list, description=f"{SHORT}: 2-3 pontos")
    reasons: list[str] = Field(default_factory=list, description="2-5 razões principais")
    risks: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list, description="avisos do guard (números não verificados, etc.)")
    data_gaps: list[str] = Field(default_factory=list, description="agentes que falharam ou não se aplicam")
    run_id: str | None = None
    payload: dict = Field(default_factory=dict, description="resumo das análises usadas")


class RatingDecision(BaseModel):
    """Saída do LLM de classificação (o guard transforma em Synthesis)."""
    rating: str = Field(description="strong_sell | sell | hold | buy | strong_buy")
    confidence: float = Field(ge=0, le=1)
    horizon: str = Field(description="horizonte da tese, ex.: '3-12 meses'")
    headline: str = Field(description=f"{SHORT}: 1 frase simples, máx. 110 caracteres, sem jargão (ex.: "
                                      "'Empresa excelente, mas o preço já desconta o bom momento')")
    key_points: list[str] = Field(description=f"{SHORT}: 2-3 pontos de máx. 60 caracteres cada, um número no máximo "
                                              "por ponto (ex.: 'Qualidade muito alta: Piotroski 9/9')")
    reasons: list[str] = Field(description="2-5 razões principais; cada número citado tem de vir do dossier")
    risks: list[str] = Field(description="2-4 riscos principais")
    bull_case: str | None = None
    bear_case: str | None = None


class IpoDeal(BaseModel):
    price_range: str | None = None
    shares_offered: float | None = None
    primary_shares: float | None = None
    secondary_shares: float | None = None
    greenshoe: str | None = None
    post_offering_shares: float | None = None
    implied_valuation_low: float | None = None
    implied_valuation_high: float | None = None
    currency: str | None = None
    underwriters: list[str] = Field(default_factory=list)
    lockup: str | None = None
    share_classes: str | None = None
    use_of_proceeds: str | None = None


class IpoSynthesis(BaseModel):
    name: str
    symbol: str | None = None
    exchange: str | None = None
    ipo_date: str | None = None
    rating: str = Field(description="subscrever | neutro | evitar")
    confidence: float = Field(ge=0, le=1)
    deal: IpoDeal
    valuation_view: str = Field(description="valorização implícita vs peers cotados (múltiplos citados)")
    financials: str = Field(description="resumo das financeiras do prospeto; 'não divulgado' quando falta")
    ipo_window: str = Field(description="como correram os IPOs recentes do setor")
    bull_case: list[str]
    bear_case: list[str]
    watch_points: list[str]
    sources: list[str] = Field(default_factory=list)
    not_disclosed: list[str] = Field(default_factory=list, description="campos que o prospeto ainda não divulga "
                                                                        "(nomes curtos, ex.: 'lock-up', 'bookrunners')")
    headline: str = ""
    pros_short: list[str] = Field(default_factory=list)
    cons_short: list[str] = Field(default_factory=list)

    @field_validator("ipo_date", mode="before")
    @classmethod
    def iso_date_only(cls, v):
        """Só a data (YYYY-MM-DD); comentários sobre a data vão para watch_points, não para aqui."""
        m = re.search(r"\d{4}-\d{2}-\d{2}", str(v or ""))
        return m.group(0) if m else None


class IpoAnalysis(IpoSynthesis):
    """Contrato do LLM pré-IPO: as versões curtas são obrigatórias (a IpoSynthesis aceita dados antigos sem elas)."""
    ipo_date: str | None = Field(default=None, description="só a data prevista de estreia, YYYY-MM-DD, ou null")
    exchange: str | None = Field(default=None, description="nome curto da bolsa, ex.: 'Nasdaq', 'Tóquio'")
    headline: str = Field(description=f"{SHORT}: 1 frase simples, máx. 110 caracteres")
    pros_short: list[str] = Field(description=f"{SHORT}: 1-2 pontos a favor, máx. 60 caracteres cada")
    cons_short: list[str] = Field(description=f"{SHORT}: 1-2 pontos contra, máx. 60 caracteres cada")
