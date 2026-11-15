"""Notícias numa só recolha (D25). Funções puras, sem rede nem LLM.

Antes havia 4 agentes LLM (4h/24h/7d/30d) a pedir as mesmas notícias à API: 0,70 USD por análise e 45% de itens
repetidos entre janelas. Agora:
  collect()  código  — junta o que as APIs dão, tira repetidos, corta a 30 dias, dá um id estável a cada item
  (LLM)      1 sessão — anota relevância/tom/resumo por id e completa com pesquisa web (news_scan_agent)
  merge()    código  — junta anotações e itens da web, recalcula as janelas pela hora de publicação
As janelas não se sobrepõem: cada item fica na mais curta que o contém ("4h", "24h", "7d", "30d").
"""
import hashlib
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime

WINDOWS = (("4h", 4), ("24h", 24), ("7d", 168), ("30d", 720))
CAPS = {"4h": 10, "24h": 12, "7d": 12, "30d": 15}       # máximo de itens por janela no resultado
TONES = {"positivo": 1, "negativo": -1, "neutro": 0}
CATEGORIES = ("earnings", "analyst", "regulatory", "product", "macro", "m&a", "legal", "management", "other")


def parse_ts(value) -> datetime | None:
    """ISO 8601 (com ou sem Z), RFC 2822 ou epoch → datetime UTC. None se não der para interpretar."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, timezone.utc)
    s = str(value).strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(s)
        except (TypeError, ValueError):
            return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def window_of(ts: datetime, now: datetime) -> str | None:
    """A janela mais curta que contém `ts`; None se tiver mais de 30 dias. Datas no futuro contam como "agora"."""
    age_h = max(0.0, (now - ts).total_seconds() / 3600)
    return next((name for name, hours in WINDOWS if age_h <= hours), None)


def canon(url: str | None) -> str:
    return re.sub(r"^https?://(www\.)?", "", (url or "").split("?")[0].split("#")[0]).rstrip("/").lower()


def norm(title: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (title or "").lower())).strip()


def item_id(url: str | None, title: str | None) -> str:
    """Id estável entre recolhas (a anotação do LLM fica em cache 1 h e a recolha muda de 10 em 10 minutos)."""
    return "n" + hashlib.sha1((canon(url) or norm(title)).encode("utf-8")).hexdigest()[:6]


def groups(items: list[dict], threshold: float = 0.75) -> list[list[int]]:
    """Agrupa itens quase iguais: mesmo URL canónico ou títulos muito parecidos."""
    out: list[list[int]] = []
    for i, it in enumerate(items):
        for g in out:
            ref = items[g[0]]
            same_url = canon(it.get("url")) and canon(it.get("url")) == canon(ref.get("url"))
            if same_url or SequenceMatcher(None, norm(it.get("title")), norm(ref.get("title"))).ratio() >= threshold:
                g.append(i)
                break
        else:
            out.append([i])
    return out


def collect(raw: list[dict], now: datetime, *, symbol: str = "", company: str = "", max_items: int = 40,
            max_recent: int = 20) -> dict:
    """Itens das APIs → lista única (mais recentes primeiro), sem repetidos, só os últimos 30 dias."""
    dated = []
    for it in raw or []:
        ts = parse_ts(it.get("published_at"))
        if ts is None or not it.get("title") or window_of(ts, now) is None:
            continue
        dated.append((ts, it))
    dated.sort(key=lambda x: x[0], reverse=True)
    unique = [dated[g[0]] for g in groups([it for _, it in dated])]
    recent = [x for x in unique if now - x[0] <= timedelta(hours=24)][:max_recent]
    older = [x for x in unique if now - x[0] > timedelta(hours=24)]
    kept = (recent + older)[:max_items]
    items = [{"id": item_id(it.get("url"), it.get("title")), "w": window_of(ts, now), "published_at": iso(ts),
              "title": str(it["title"])[:200], "source": it.get("source") or it.get("provider"), "url": it.get("url"),
              "snippet": re.sub(r"\s+", " ", str(it.get("summary") or ""))[:240] or None} for ts, it in kept]
    counts = {name: sum(i["w"] == name for i in items) for name, _ in WINDOWS}
    gaps = [f"sem itens das APIs em {name}" for name, _ in WINDOWS if not counts[name]]
    return {"symbol": symbol, "company": company, "fetched_at": iso(now), "items": items, "counts": counts,
            "gaps": gaps, "dropped": len(raw or []) - len(items)}


def legacy_digest(windows: dict[str, dict | None]) -> dict | None:
    """Análises anteriores à Fase 10 gravaram 4 relatórios (news_4h…news_30d): junta-os no formato novo, sem
    repetidos, para os cartões antigos e para repetir nós com dados gravados (tools/replay.py)."""
    if all(v is None for v in windows.values()):
        return None
    items = []
    for name, _ in WINDOWS:
        for it in ((windows.get(name) or {}).get("items") or []):
            items.append({"w": name, "title": it.get("title"), "source": it.get("source"), "url": it.get("url"),
                          "published_at": it.get("published_at"), **_clean_annotation(it), "triaged": True})
    items = [items[g[0]] for g in groups(items)]
    first = next((v for v in windows.values() if v), {})
    return {"symbol": first.get("ticker"), "company": first.get("company"), "generated_at": first.get("searched_at"),
            "scanned_at": first.get("searched_at"), "untriaged": 0, "items": items, "note": None,
            "per_window": {name: sum(i["w"] == name for i in items) for name, _ in WINDOWS}}


def _clean_annotation(a: dict) -> dict:
    rel = a.get("relevance")
    try:
        rel = max(1, min(5, int(rel)))
    except (TypeError, ValueError):
        rel = None
    tone = str(a.get("tone") or "neutro").strip().lower()
    cat = str(a.get("category") or "other").strip().lower()
    return {"relevance": rel, "tone": tone if tone in TONES else "neutro",
            "category": cat if cat in CATEGORIES else "other", "summary": (a.get("summary") or None)}


def merge(feed: dict | None, scan: dict | None, now: datetime, *, symbol: str = "", company: str = "") -> dict:
    """Recolha das APIs + anotações do LLM + itens da web → notícias por janela (recalculada agora).

    - item da recolha com anotação → triado;
    - sem anotação e publicado antes da triagem → o LLM achou irrelevante: sai;
    - sem anotação e publicado depois da triagem (ou sem triagem nenhuma) → entra "por triar": o título chega já,
      sem esperar por nova sessão LLM (é assim que a janela de 4 h nunca fica velha).
    """
    feed, scan = feed or {}, scan or {}
    notes = {a.get("id"): _clean_annotation(a) for a in scan.get("annotations") or [] if a.get("id")}
    scanned_at = parse_ts(scan.get("scanned_at")) if scan else None
    items = []
    for it in feed.get("items") or []:
        ts = parse_ts(it.get("published_at"))
        if ts is None:
            continue
        base = {"title": it.get("title"), "source": it.get("source"), "url": it.get("url"), "published_at": iso(ts)}
        if it.get("id") in notes:
            n = notes[it["id"]]
            items.append({**base, **n, "summary": n["summary"] or it.get("snippet"), "triaged": True, "_ts": ts})
        elif not scan or scanned_at is None or ts > scanned_at:
            items.append({**base, "category": "other", "relevance": None, "tone": "neutro",
                          "summary": it.get("snippet"), "triaged": False, "_ts": ts})
    for w in scan.get("web_items") or []:
        ts = parse_ts(w.get("published_at"))
        if ts is None or not w.get("title"):
            continue
        items.append({"title": str(w["title"])[:200], "source": w.get("source"), "url": w.get("url"),
                      "published_at": iso(ts), **_clean_annotation(w), "triaged": True, "from_web": True,
                      "time_confirmed": bool(w.get("time_confirmed")), "_ts": ts})
    items = [items[g[0]] for g in groups(sorted(items, key=lambda i: (not i["triaged"], -i["_ts"].timestamp())))]
    out, per_window = [], {}
    for name, _ in WINDOWS:
        bucket = [i for i in items if window_of(i["_ts"], now) == name]
        bucket.sort(key=lambda i: (-(i["relevance"] or 0), -i["_ts"].timestamp()))
        bucket = bucket[:CAPS[name]]
        per_window[name] = len(bucket)
        out += [{"w": name, **{k: v for k, v in i.items() if k != "_ts"}} for i in bucket]
    return {"symbol": symbol or feed.get("symbol"), "company": company or feed.get("company"),
            "generated_at": iso(now), "scanned_at": iso(scanned_at) if scanned_at else None,
            "per_window": per_window, "untriaged": sum(not i["triaged"] for i in out), "items": out,
            "note": None if scan else "sem triagem do LLM nesta execução: só títulos das APIs, por classificar"}
