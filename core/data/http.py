"""HTTP partilhado pelos fornecedores: retries e classificação de erros."""
import json
import time
import urllib.error
import urllib.request

UA = {"User-Agent": "Agentock/0.1"}


class ProviderError(Exception):
    """kind: blocked (401/402/403, plano não cobre) | quota (429) | notfound | error"""

    def __init__(self, kind: str, msg: str = ""):
        super().__init__(f"{kind}: {msg}")
        self.kind = kind
        self.msg = msg


def body_error(d) -> str | None:
    """Erros que algumas APIs devolvem com HTTP 200."""
    if not isinstance(d, dict):
        return None
    for k in ("Information", "Note", "Error Message", "error"):
        if d.get(k):
            v = d[k]
            return str(v.get("message", v) if isinstance(v, dict) else v)
    if d.get("status") == "error" or (isinstance(d.get("code"), int) and d["code"] >= 400):
        return str(d.get("message"))
    return None


def _classify_body(msg: str) -> str:
    m = msg.lower()
    if any(w in m for w in ("premium", "subscription", "upgrade", "not available", "access", "plan")):
        return "blocked"
    if any(w in m for w in ("rate", "spreading out", "too many", "limit")):
        return "quota"
    return "error"


def fetch(url: str, headers: dict | None = None, *, raw: bool = False, timeout: int = 30, retries: int = 2):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                text = r.read().decode("utf-8", "replace")
            break
        except urllib.error.HTTPError as e:
            body = e.read()[:300].decode("utf-8", "replace")
            if e.code in (401, 402, 403):
                raise ProviderError("blocked", f"HTTP {e.code} {body}")
            if e.code == 404:
                raise ProviderError("notfound", f"HTTP 404 {body}")
            if e.code == 422:
                raise ProviderError("notfound", f"HTTP 422 {body}")
            if e.code == 429:
                raise ProviderError("quota", f"HTTP 429 {body}")
            if attempt == retries:
                raise ProviderError("error", f"HTTP {e.code} {body}")
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == retries:
                raise ProviderError("error", str(e))
        time.sleep(1.5 * (attempt + 1))
    if raw:
        return text
    d = json.loads(text)
    if (msg := body_error(d)):
        raise ProviderError(_classify_body(msg), msg[:200])
    return d
