"""Envia um alerta de mudança de classificação REAL para o Telegram, a partir de dados simulados.

Usa uma base de dados em memória (não toca no histórico verdadeiro). A mensagem vai marcada como TESTE.
Uso: python tools/test_alert.py
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import core.env  # noqa: E402,F401
from core import db  # noqa: E402
from core.schemas import Synthesis  # noqa: E402

spec = importlib.util.spec_from_file_location("_alert", ROOT / "agents" / "change_alert_agent" / "run.py")
alert = importlib.util.module_from_spec(spec)
spec.loader.exec_module(alert)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    conn = db.connect(":memory:")
    base = dict(ticker="TESTE.AAPL", confidence=0.6, price=356.4, currency="USD", market="US", version="v2")
    old = Synthesis(**base, rating="hold", reasons=["Preço acima do alvo médio dos analistas", "RSI neutro"])
    new = Synthesis(**base, rating="strong_buy", reasons=["Preço acima do alvo médio dos analistas",
                                                         "Resultados muito acima das estimativas (simulado)"])
    for s in (old, new):
        db.save_run(conn, ticker=s.ticker, rating=2 if s.rating == "strong_buy" else 0, confidence=s.confidence,
                    price=s.price, reasons=s.reasons, payload={})
        out = alert.run(s, conn=conn)
    print(out)


if __name__ == "__main__":
    main()
