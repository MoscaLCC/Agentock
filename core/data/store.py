"""Cache com TTL e livro de quotas, em SQLite (data/cache.db).

Thread-safe: os agentes de script correm em threads paralelas e partilham esta ligação; todas as operações
passam por um lock (o sqlite3 não aceita uso concorrente da mesma ligação).
"""
import json
import sqlite3
import threading
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "cache.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT, provider TEXT, created REAL, expires REAL);
CREATE TABLE IF NOT EXISTS quota_calls (provider TEXT, ts REAL, weight INTEGER DEFAULT 1);
CREATE INDEX IF NOT EXISTS idx_quota ON quota_calls(provider, ts);
CREATE TABLE IF NOT EXISTS quota_blocked (provider TEXT, capability TEXT, symbol TEXT, until REAL, reason TEXT,
                                          PRIMARY KEY (provider, capability, symbol));
"""

WINDOWS = {"per_minute": 60, "per_hour": 3600, "per_day": 86400, "per_month": 30 * 86400}


class Store:
    def __init__(self, path: str | Path | None = None, clock=time.time):
        p = str(path or DB_PATH)
        if p != ":memory:":
            Path(p).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(p, check_same_thread=False, timeout=30)
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(SCHEMA)
        self.clock = clock

    def _q(self, sql: str, args=(), *, one=False, commit=False):
        with self.lock:
            cur = self.conn.execute(sql, args)
            res = cur.fetchone() if one else cur.fetchall()
            if commit:
                self.conn.commit()
            return res

    # ---- cache
    def cache_get(self, key: str):
        row = self._q("SELECT value, provider, created FROM cache WHERE key=? AND expires>?", (key, self.clock()), one=True)
        return (json.loads(row[0]), row[1], row[2]) if row else None

    def cache_set(self, key: str, value, provider: str, ttl: float) -> None:
        now = self.clock()
        self._q("INSERT OR REPLACE INTO cache VALUES (?,?,?,?,?)",
                (key, json.dumps(value, ensure_ascii=False, default=str), provider, now, now + ttl), commit=True)

    # ---- quotas
    def usage(self, provider: str, window: str) -> int:
        return self._q("SELECT COALESCE(SUM(weight),0) FROM quota_calls WHERE provider=? AND ts>?",
                       (provider, self.clock() - WINDOWS[window]), one=True)[0]

    def allow(self, provider: str, limits: dict, weight: int = 1) -> bool:
        with self.lock:
            if self.is_blocked(provider, "*", "*"):
                return False
            return all(self.usage(provider, name) + weight <= limit for name, limit in (limits or {}).items())

    def record(self, provider: str, weight: int = 1) -> None:
        self._q("INSERT INTO quota_calls VALUES (?,?,?)", (provider, self.clock(), weight), commit=True)

    def block(self, provider: str, capability: str, symbol: str, seconds: float, reason: str = "") -> None:
        self._q("INSERT OR REPLACE INTO quota_blocked VALUES (?,?,?,?,?)",
                (provider, capability, symbol, self.clock() + seconds, reason[:200]), commit=True)

    def is_blocked(self, provider: str, capability: str, symbol: str) -> bool:
        return self._q("SELECT 1 FROM quota_blocked WHERE provider=? AND capability=? AND symbol=? AND until>?",
                       (provider, capability, symbol, self.clock()), one=True) is not None

    def prune(self) -> None:
        now = self.clock()
        with self.lock:
            self.conn.execute("DELETE FROM quota_calls WHERE ts<?", (now - 31 * 86400,))
            self.conn.execute("DELETE FROM cache WHERE expires<?", (now,))
            self.conn.execute("DELETE FROM quota_blocked WHERE until<?", (now,))
            self.conn.commit()
