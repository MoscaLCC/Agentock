"""Memória/histórico em SQLite."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "agentock.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL, ts TEXT NOT NULL,
    rating INTEGER NOT NULL, confidence REAL, price REAL,
    reasons TEXT, payload TEXT,
    ret_1d REAL, ret_7d REAL, ret_30d REAL          -- preenchidos depois (avaliação)
);
CREATE INDEX IF NOT EXISTS idx_runs_ticker_ts ON runs(ticker, ts);
CREATE TABLE IF NOT EXISTS state (
    ticker TEXT PRIMARY KEY,
    confirmed INTEGER NOT NULL, confirmed_ts TEXT NOT NULL,
    pending INTEGER, pending_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL, ts TEXT NOT NULL,
    old_rating INTEGER, new_rating INTEGER, kind TEXT,
    message TEXT, sent INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS agent_outputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL, node TEXT, agent TEXT NOT NULL, ticker TEXT, ts TEXT NOT NULL,
    status TEXT NOT NULL, cached INTEGER NOT NULL DEFAULT 0,
    output TEXT, error TEXT, cost_usd REAL, duration_ms INTEGER, turns INTEGER
);
CREATE INDEX IF NOT EXISTS idx_outputs_run ON agent_outputs(run_id);
CREATE INDEX IF NOT EXISTS idx_outputs_ticker ON agent_outputs(ticker, ts);
CREATE TABLE IF NOT EXISTS agent_cache (
    key TEXT PRIMARY KEY, agent TEXT, output TEXT, created REAL, expires REAL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


SCHEMA_EXTRA = """
CREATE TABLE IF NOT EXISTS ipo_ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, run_id TEXT, name TEXT NOT NULL, symbol TEXT, exchange TEXT, ipo_date TEXT,
    rating INTEGER NOT NULL, confidence REAL, price_range TEXT, ipo_price REAL, payload TEXT,
    ret_day1 REAL, ret_day30 REAL, ret_day180 REAL, evaluated_at TEXT
);
CREATE TABLE IF NOT EXISTS seen (
    key TEXT PRIMARY KEY, kind TEXT, ts TEXT, payload TEXT
);
CREATE TABLE IF NOT EXISTS universe_progress (
    batch_id TEXT, ticker TEXT, status TEXT, run_id TEXT, ts TEXT, PRIMARY KEY (batch_id, ticker)
);
"""

# colunas acrescentadas depois da criação inicial (migração automática)
MIGRATIONS = {
    "runs": {"version": "TEXT", "market": "TEXT", "currency": "TEXT", "run_id": "TEXT", "bench_symbol": "TEXT",
             "bench_1d": "REAL", "bench_7d": "REAL", "bench_30d": "REAL", "evaluated_at": "TEXT"},
    "agent_outputs": {"usage": "TEXT"},  # tokens por modelo (JSON), desde a Fase 10
    "state": {"pending_ts": "TEXT", "last_run_id": "TEXT"},  # histerese: 2.ª observação tem de ser outra análise
    "alerts": {"run_id": "TEXT"},
}


def _migrate(conn) -> None:
    for table, cols in MIGRATIONS.items():
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col, typ in cols.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    # uma análise grava uma só classificação (um retry ou uma retoma não duplicam o histórico)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_run_id ON runs(run_id) WHERE run_id IS NOT NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_expires ON agent_cache(expires)")
    conn.commit()


_READY: set[str] = set()


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    p = str(path or DB_PATH)
    if p != ":memory:":
        Path(p).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if p == ":memory:" or p not in _READY:  # schema e migrações uma vez por processo e por base
        if p != ":memory:":
            conn.execute("PRAGMA journal_mode=WAL")   # leitores (bot) não bloqueiam o escritor (análise)
        conn.executescript(SCHEMA + SCHEMA_EXTRA)
        _migrate(conn)
        _READY.add(p)
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def save_run(conn, *, ticker, rating: int, confidence, price, reasons, payload, version: str = "v1",
             market: str | None = None, currency: str | None = None, run_id: str | None = None) -> int:
    if run_id and (row := conn.execute("SELECT id FROM runs WHERE run_id=?", (run_id,)).fetchone()):
        return row["id"]  # idempotente: esta análise já gravou a sua classificação
    cur = conn.execute(
        "INSERT INTO runs(ticker, ts, rating, confidence, price, reasons, payload, version, market, currency, run_id)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (ticker, now(), int(rating), confidence, price, json.dumps(reasons, ensure_ascii=False),
         json.dumps(payload, ensure_ascii=False, default=str), version, market, currency, run_id),
    )
    conn.commit()
    return cur.lastrowid


def save_ipo_rating(conn, *, name, symbol, exchange, ipo_date, rating: int, confidence, price_range, payload,
                    run_id=None) -> int:
    cur = conn.execute(
        "INSERT INTO ipo_ratings(ts, run_id, name, symbol, exchange, ipo_date, rating, confidence, price_range, payload)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (now(), run_id, name, symbol, exchange, ipo_date, int(rating), confidence, price_range,
         json.dumps(payload, ensure_ascii=False, default=str)),
    )
    conn.commit()
    return cur.lastrowid


def was_seen(conn, key: str) -> bool:
    return conn.execute("SELECT 1 FROM seen WHERE key=?", (key,)).fetchone() is not None


def mark_seen(conn, key: str, kind: str, payload=None) -> None:
    conn.execute("INSERT OR IGNORE INTO seen VALUES (?,?,?,?)",
                 (key, kind, now(), json.dumps(payload, ensure_ascii=False, default=str)))
    conn.commit()


def save_agent_output(conn, *, run_id, node, agent, ticker, status, cached, output, error, cost_usd,
                      duration_ms, turns, usage=None) -> None:
    conn.execute(
        "INSERT INTO agent_outputs(run_id, node, agent, ticker, ts, status, cached, output, error, cost_usd,"
        " duration_ms, turns, usage) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (run_id, node, agent, ticker, now(), status, int(cached), output, error, cost_usd, duration_ms, turns, usage),
    )
    conn.commit()


def agent_cache_get(conn, key: str):
    import time
    row = conn.execute("SELECT output FROM agent_cache WHERE key=? AND expires>?", (key, time.time())).fetchone()
    return row["output"] if row else None


def prune(conn, keep_days: int = 30) -> dict:
    """Limpeza: cache expirada e outputs de nós com mais de `keep_days` (o histórico `runs` nunca se apaga)."""
    import time
    a = conn.execute("DELETE FROM agent_cache WHERE expires < ?", (time.time(),)).rowcount
    b = conn.execute("DELETE FROM agent_outputs WHERE ts < datetime('now', ?) AND run_id NOT IN "
                     "(SELECT run_id FROM runs WHERE run_id IS NOT NULL)", (f"-{int(keep_days)} days",)).rowcount
    conn.commit()
    return {"cache": a, "outputs": b}


def agent_cache_set(conn, key: str, agent: str, output: str, ttl: int) -> None:
    import time
    t = time.time()
    conn.execute("INSERT OR REPLACE INTO agent_cache VALUES (?,?,?,?,?)", (key, agent, output, t, t + ttl))
    conn.commit()


def history(conn, ticker: str, limit: int = 20) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM runs WHERE ticker=? ORDER BY ts DESC, id DESC LIMIT ?", (ticker, limit)
    ).fetchall()
