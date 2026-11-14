"""Escala ordinal fixa de classificação — permite medir a dimensão de uma mudança."""
from enum import IntEnum


class Rating(IntEnum):
    STRONG_SELL = -2
    SELL = -1
    HOLD = 0
    BUY = 1
    STRONG_BUY = 2

    @property
    def label(self) -> str:
        return {
            -2: "Venda forte", -1: "Venda", 0: "Hold", 1: "Compra", 2: "Compra forte",
        }[int(self)]

    @classmethod
    def parse(cls, value) -> "Rating":
        if isinstance(value, cls):
            return value
        if isinstance(value, int):
            return cls(value)
        key = str(value).strip().lower().replace(" ", "_").replace("-", "_")
        aliases = {
            "strong_sell": cls.STRONG_SELL, "venda_forte": cls.STRONG_SELL,
            "sell": cls.SELL, "venda": cls.SELL, "vender": cls.SELL,
            "hold": cls.HOLD, "manter": cls.HOLD, "neutral": cls.HOLD,
            "buy": cls.BUY, "compra": cls.BUY, "comprar": cls.BUY,
            "strong_buy": cls.STRONG_BUY, "compra_forte": cls.STRONG_BUY,
        }
        if key in aliases:
            return aliases[key]
        raise ValueError(f"Classificação desconhecida: {value!r}")
