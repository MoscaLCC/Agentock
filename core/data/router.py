"""Router de dados: escolhe o fornecedor por dado e mercado, com cache, quotas e fallback.

    r = get_router()
    res = r.get("quote", "0700.HK")      # DataResult(provider='yfinance', data={...})
    res = r.get("news", "AAPL")          # merge: junta Finnhub + Alpaca + yfinance, deduplicado
    r.cross_check_close("600519.SS")     # compara o último fecho entre 2 fontes
"""
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .. import env  # noqa: F401  (carrega o .env)
from .http import ProviderError
from .markets import market_of
from .providers import Provider, default_providers
from .store import Store

CONFIG = Path(__file__).resolve().parents[2] / "config" / "data_sources.yaml"


@dataclass
class DataResult:
    capability: str
    symbol: str | None
    provider: str
    data: object
    fetched_at: float
    cached: bool = False
    tried: list[str] = field(default_factory=list)


class DataUnavailable(Exception):
    def __init__(self, capability, symbol, tried):
        super().__init__(f"{capability} {symbol}: nenhum fornecedor respondeu ({'; '.join(tried)})")
        self.tried = tried


def _empty(x) -> bool:
    return x is None or x == [] or x == {}


def _dedupe(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for it in items:
        k = (it.get("url") or "").split("?")[0].rstrip("/").lower() or (it.get("title") or "").strip().lower()
        k = k or json.dumps(it, sort_keys=True, default=str)
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


class Router:
    def __init__(self, config: dict | None = None, store: Store | None = None,
                 providers: dict[str, Provider] | None = None):
        self.cfg = config or yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        self.store = store or Store()
        self.providers = providers if providers is not None else default_providers()

    # ------------------------------------------------------------------ helpers
    def chain(self, capability: str, symbol: str | None) -> list[str]:
        routes = self.cfg["routes"].get(capability) or {}
        return list(routes.get(market_of(symbol)) or routes.get("default") or [])

    def limits(self, provider: str) -> dict:
        return (self.cfg["providers"].get(provider) or {}).get("limits") or {}

    def _key(self, capability, symbol, params) -> str:
        return f"{capability}|{symbol}|{json.dumps(params, sort_keys=True, default=str)}"

    def _try(self, name: str, capability: str, symbol, params: dict):
        """Devolve (data, motivo_de_falha)."""
        p = self.providers.get(name)
        if p is None or not p.supports(capability):
            return None, f"{name}: não suporta"
        if not p.configured():
            return None, f"{name}: sem chave"
        sym = symbol or "*"
        if self.store.is_blocked(name, capability, sym):
            return None, f"{name}: bloqueado (memória)"
        if not self.store.allow(name, self.limits(name), p.weight(capability)):
            return None, f"{name}: quota"
        self.store.record(name, p.weight(capability))
        try:
            data = p.call(capability, symbol, **params)
        except ProviderError as e:
            if e.kind in ("blocked", "notfound"):
                self.store.block(name, capability, sym, self.cfg.get("blocked_days", 7) * 86400, e.msg)
            elif e.kind == "quota":
                self.store.block(name, "*", "*", self.cfg.get("cooldown_seconds", 120), e.msg)
            return None, f"{name}: {e.kind}"
        except Exception as e:  # erro inesperado de biblioteca/formato: não bloqueia, só passa à frente
            return None, f"{name}: {type(e).__name__}: {str(e)[:80]}"
        if _empty(data):
            return None, f"{name}: vazio"
        return data, None

    # ------------------------------------------------------------------ API
    def get(self, capability: str, symbol: str | None = None, *, use_cache: bool = True, **params) -> DataResult:
        key = self._key(capability, symbol, params)
        if use_cache and (hit := self.store.cache_get(key)):
            data, provider, created = hit
            return DataResult(capability, symbol, provider, data, created, cached=True)

        tried, merged, used = [], [], []
        merge = capability in self.cfg.get("merge", [])
        for name in self.chain(capability, symbol):
            data, why = self._try(name, capability, symbol, params)
            if why:
                tried.append(why)
                continue
            if not merge:
                self.store.cache_set(key, data, name, self.cfg["ttl"].get(capability, 300))
                return DataResult(capability, symbol, name, data, time.time(), tried=tried)
            for item in data:
                item.setdefault("provider", name)
            merged += data
            used.append(name)

        if merge and merged:
            data = _dedupe(merged)
            if capability == "news":
                data.sort(key=lambda n: n.get("published_at") or "", reverse=True)
            provider = "+".join(used)
            self.store.cache_set(key, data, provider, self.cfg["ttl"].get(capability, 300))
            return DataResult(capability, symbol, provider, data, time.time(), tried=tried)
        raise DataUnavailable(capability, symbol, tried)

    def cross_check_close(self, symbol: str, threshold_pct: float = 1.0) -> dict:
        """Último fecho comum entre as duas primeiras fontes EOD que respondam."""
        sources = []
        for name in self.chain("eod", symbol):
            data, _ = self._try(name, "eod", symbol, {"days": 10})
            if data:
                sources.append((name, {b["t"]: b["c"] for b in data if b.get("c")}))
            if len(sources) == 2:
                break
        if len(sources) < 2:
            return {"symbol": symbol, "checked": False, "reason": "menos de 2 fontes disponíveis"}
        (a, da), (b, db) = sources
        common = sorted(set(da) & set(db))
        if not common:
            return {"symbol": symbol, "checked": False, "reason": f"sem datas comuns entre {a} e {b}"}
        d = common[-1]
        diff = abs(da[d] / db[d] - 1) * 100
        return {"symbol": symbol, "checked": True, "date": d, a: da[d], b: db[d],
                "diff_pct": round(diff, 3), "suspect": diff > threshold_pct}


_ROUTER: Router | None = None


def get_router() -> Router:
    global _ROUTER
    if _ROUTER is None:
        _ROUTER = Router()
    return _ROUTER
