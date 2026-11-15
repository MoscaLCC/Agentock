"""Fila persistente de tarefas do bot (SQLite) + estado pequeno (kv), lista de ações seguidas e definições.

Uma tarefa nunca se perde: fica gravada antes de se responder ao utilizador e sobrevive a reinícios.

  queued ──► running ──► done | failed | cancelled
                │
                └──► waiting (limite de utilização atingido; volta a queued depois de `not_before`)

- Deduplicação: um pedido igual a outro ainda ativo (mesma `dedupe_key`) não cria nova tarefa.
- Idempotência: o mesmo update do Telegram (`update_id`) nunca cria duas tarefas.
- Retoma: no arranque, tarefas `running` de um processo que morreu voltam a `queued` com o mesmo `run_id`
  (os nós já gravados são reaproveitados); à 2.ª falha ficam `failed`.
"""
import json
import os
from datetime import datetime, timedelta, timezone

ACTIVE = ("queued", "running", "waiting")
SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL, args TEXT NOT NULL DEFAULT '{}', dedupe_key TEXT,
    state TEXT NOT NULL DEFAULT 'queued', update_id INTEGER UNIQUE, status_msg_id INTEGER, run_id TEXT,
    attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 2, not_before TEXT,
    created TEXT NOT NULL, started TEXT, finished TEXT, heartbeat TEXT, worker_pid INTEGER,
    cancel_requested INTEGER NOT NULL DEFAULT 0, error TEXT, result TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_active ON jobs(dedupe_key)
    WHERE dedupe_key IS NOT NULL AND state IN ('queued', 'running', 'waiting');
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state, id);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS watchlist (ticker TEXT PRIMARY KEY, name TEXT, added TEXT NOT NULL);
"""
DEFAULTS = {"rating_version": "v2", "auto_analysis": "off", "daily_summary": "off", "summary_hour": "08:30"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init(conn) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


# ------------------------------------------------------------------ kv e definições
def kv_get(conn, key: str, default=None):
    row = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row and row[0] is not None else default


def kv_set(conn, key: str, value) -> None:
    conn.execute("INSERT INTO kv(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, json.dumps(value, ensure_ascii=False)))
    conn.commit()


def setting(conn, name: str):
    return kv_get(conn, f"set:{name}", DEFAULTS.get(name))


def set_setting(conn, name: str, value) -> None:
    if name not in DEFAULTS:
        raise KeyError(name)
    kv_set(conn, f"set:{name}", value)


# ------------------------------------------------------------------ lista de ações seguidas
def watch_add(conn, ticker: str, name: str | None = None) -> bool:
    cur = conn.execute("INSERT OR IGNORE INTO watchlist(ticker, name, added) VALUES (?,?,?)", (ticker, name, now()))
    conn.commit()
    return cur.rowcount > 0


def watch_remove(conn, ticker: str) -> bool:
    cur = conn.execute("DELETE FROM watchlist WHERE ticker=?", (ticker,))
    conn.commit()
    return cur.rowcount > 0


def watchlist(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT ticker, name, added FROM watchlist ORDER BY added, ticker")]


# ------------------------------------------------------------------ fila
def _row(r) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    d["args"] = json.loads(d.get("args") or "{}")
    return d


def get(conn, job_id: int) -> dict | None:
    return _row(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())


def enqueue(conn, kind: str, args: dict, *, dedupe_key: str | None = None, update_id: int | None = None,
            max_queue: int = 60) -> tuple[dict | None, str]:
    """(tarefa, "new" | "duplicate" | "seen" | "full"). `duplicate`: já há uma igual ativa (devolve essa).
    `seen`: este update do Telegram já tinha sido tratado. `full`: fila cheia."""
    if update_id is not None:
        seen = conn.execute("SELECT * FROM jobs WHERE update_id=?", (update_id,)).fetchone()
        if seen:
            return _row(seen), "seen"
    if dedupe_key:
        dup = conn.execute(f"SELECT * FROM jobs WHERE dedupe_key=? AND state IN {ACTIVE}", (dedupe_key,)).fetchone()
        if dup:
            return _row(dup), "duplicate"
    if conn.execute(f"SELECT COUNT(*) FROM jobs WHERE state IN {ACTIVE}").fetchone()[0] >= max_queue:
        return None, "full"
    cur = conn.execute("INSERT INTO jobs(kind, args, dedupe_key, update_id, created) VALUES (?,?,?,?,?)",
                       (kind, json.dumps(args, ensure_ascii=False), dedupe_key, update_id, now()))
    conn.commit()
    return get(conn, cur.lastrowid), "new"


def claim(conn, pid: int | None = None) -> dict | None:
    """A tarefa mais antiga pronta a correr passa a `running` (uma de cada vez: há um só worker)."""
    t = now()
    conn.execute("UPDATE jobs SET state='queued', not_before=NULL WHERE state='waiting' AND not_before <= ?", (t,))
    row = conn.execute("SELECT id FROM jobs WHERE state='queued' AND (not_before IS NULL OR not_before <= ?)"
                       " ORDER BY id LIMIT 1", (t,)).fetchone()
    if row is None:
        conn.commit()
        return None
    conn.execute("UPDATE jobs SET state='running', started=COALESCE(started, ?), heartbeat=?, worker_pid=?,"
                 " attempts=attempts+1, cancel_requested=0 WHERE id=?", (t, t, pid or os.getpid(), row[0]))
    conn.commit()
    return get(conn, row[0])


def update(conn, job_id: int, **fields) -> None:
    if not fields:
        return
    if "result" in fields and not isinstance(fields["result"], (str, type(None))):
        fields["result"] = json.dumps(fields["result"], ensure_ascii=False, default=str)
    cols = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))
    conn.commit()


def beat(conn, job_id: int) -> None:
    update(conn, job_id, heartbeat=now())


def finish(conn, job_id: int, state: str, *, error: str | None = None, result=None) -> None:
    assert state in ("done", "failed", "cancelled"), state
    update(conn, job_id, state=state, finished=now(), error=error, result=result)


def wait_until(conn, job_id: int, when: datetime, reason: str) -> None:
    """Limite de utilização: a tarefa espera e é retomada sozinha depois de `when` (com o mesmo run_id)."""
    update(conn, job_id, state="waiting", not_before=when.astimezone(timezone.utc).isoformat(timespec="seconds"),
           error=reason)


def request_cancel(conn, job_id: int) -> str | None:
    """Estado anterior da tarefa, ou None se não existir. Em fila ou à espera: cancela já; a correr: marca o pedido."""
    j = get(conn, job_id)
    if j is None:
        return None
    if j["state"] in ("queued", "waiting"):
        finish(conn, job_id, "cancelled", error="cancelada pelo utilizador")
    elif j["state"] == "running":
        update(conn, job_id, cancel_requested=1)
    return j["state"]


def cancel_requested(conn, job_id: int) -> bool:
    row = conn.execute("SELECT cancel_requested FROM jobs WHERE id=?", (job_id,)).fetchone()
    return bool(row and row[0])


def recover(conn) -> dict:
    """No arranque: o que estava `running` ficou órfão (o processo morreu). Volta à fila ou falha de vez."""
    resumed, failed = [], []
    for r in conn.execute("SELECT * FROM jobs WHERE state='running'").fetchall():
        if r["attempts"] < r["max_attempts"]:
            conn.execute("UPDATE jobs SET state='queued', worker_pid=NULL WHERE id=?", (r["id"],))
            resumed.append(_row(r))
        else:
            conn.execute("UPDATE jobs SET state='failed', finished=?, error=? WHERE id=?",
                         (now(), "interrompida duas vezes por reinício do sistema", r["id"]))
            failed.append(_row(r))
    conn.commit()
    return {"resumed": resumed, "failed": failed}


def active(conn) -> list[dict]:
    return [_row(r) for r in conn.execute(f"SELECT * FROM jobs WHERE state IN {ACTIVE} ORDER BY"
                                          " CASE state WHEN 'running' THEN 0 ELSE 1 END, id")]


def recent(conn, limit: int = 5) -> list[dict]:
    return [_row(r) for r in conn.execute("SELECT * FROM jobs WHERE state NOT IN ('queued','running','waiting')"
                                          " ORDER BY id DESC LIMIT ?", (limit,))]


def running(conn) -> dict | None:
    return _row(conn.execute("SELECT * FROM jobs WHERE state='running' ORDER BY id LIMIT 1").fetchone())


def position(conn, job_id: int) -> int:
    """Quantas tarefas ativas estão à frente desta."""
    return conn.execute(f"SELECT COUNT(*) FROM jobs WHERE state IN {ACTIVE} AND id < ?", (job_id,)).fetchone()[0]


def prune(conn, keep_days: int = 30) -> int:
    limit = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat(timespec="seconds")
    n = conn.execute("DELETE FROM jobs WHERE state IN ('done','failed','cancelled') AND finished < ?", (limit,)).rowcount
    conn.commit()
    return n
