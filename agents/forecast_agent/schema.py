from pydantic import BaseModel, Field, model_validator


class Scenario(BaseModel):
    name: str = Field(description="bear | base | bull")
    probability: float = Field(ge=0, le=1)
    price_1m: float
    price_3m: float
    price_12m: float
    drivers: list[str] = Field(description="1-3 fatores que levam a este cenário")


class Forecast(BaseModel):
    scenarios: list[Scenario] = Field(description="exatamente 3: bear, base, bull")
    expected_12m: float | None = Field(default=None, description="média ponderada pelas probabilidades (calculada)")
    expected_return_12m_pct: float | None = None
    summary: str

    @model_validator(mode="after")
    def coherent(self):
        """Probabilidades normalizadas para somar 1; preços ordenados bear ≤ base ≤ bull em cada horizonte."""
        order = {"bear": 0, "base": 1, "bull": 2}
        self.scenarios.sort(key=lambda s: order.get(s.name, 9))
        tot = sum(s.probability for s in self.scenarios) or 1
        for s in self.scenarios:
            s.probability = round(s.probability / tot, 3)
        for h in ("price_1m", "price_3m", "price_12m"):
            vals = sorted(getattr(s, h) for s in self.scenarios)
            for s, v in zip(self.scenarios, vals):
                setattr(s, h, v)
        self.expected_12m = round(sum(s.probability * s.price_12m for s in self.scenarios), 4)
        return self
