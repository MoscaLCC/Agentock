"""Agente de avaliação: invólucro de tools/evaluation.py para correr dentro de um fluxo."""
from tools import evaluation


def run(backfill=True):
    bf = evaluation.backfill() if backfill else None
    rep = evaluation.build_report()
    evaluation.report_text(rep)
    return {"backfill": bf, "report": rep}
