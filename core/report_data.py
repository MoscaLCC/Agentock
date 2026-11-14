"""Junta os outputs de uma análise gravada (para o cartão, o detalhe e os botões do Telegram)."""
import json


def run_outputs(conn, run_id: str) -> dict:
    rows = conn.execute("SELECT node, output FROM agent_outputs WHERE run_id=? AND status='ok' AND output IS NOT NULL",
                        (run_id,)).fetchall()
    return {r["node"]: json.loads(r["output"]) for r in rows}


def latest(conn, ticker: str) -> dict | None:
    """Última classificação gravada + outputs de todos os nós dessa execução."""
    row = conn.execute("SELECT * FROM runs WHERE ticker=? ORDER BY id DESC LIMIT 1", (ticker,)).fetchone()
    return from_row(conn, row) if row else None


def by_run(conn, run_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM runs WHERE run_id=? ORDER BY id DESC LIMIT 1", (run_id,)).fetchone()
    return from_row(conn, row) if row else None


def from_row(conn, row) -> dict:
    out = run_outputs(conn, row["run_id"]) if row["run_id"] else {}
    return {"run": dict(row), "payload": json.loads(row["payload"] or "{}"),
            "reasons": json.loads(row["reasons"] or "[]"), "outputs": out}
