"""Guard: verifica números da decisão contra o dossier e monta a Synthesis.

Os hooks só veem chamadas a ferramentas, não a resposta final — por isso esta verificação é um nó de script.
"""
import re

from core.schemas import Synthesis
from core.util import as_dict

TOKEN = re.compile(r"(?<![\w.,])[-+]?\d[\d.,   ]*\d(?!\w)|(?<![\w.,])[-+]?\d(?![\w.,]\d)")
MULT = [(re.compile(r"^\s*(biliões|bilião|tri(?:llion)?s?|t\b)", re.I), 1e12),
        (re.compile(r"^\s*(mil milhões|bi(?:llion)?s?|mm\b|b\b|bn\b)", re.I), 1e9),
        (re.compile(r"^\s*(milhões|milhão|mi(?:llion)?s?|m\b|mn\b)", re.I), 1e6),
        (re.compile(r"^\s*(mil|k\b)", re.I), 1e3)]
IGNORE = {50.0, 52.0, 100.0, 200.0, 250.0, 252.0, 365.0}


def parse(token: str) -> list[tuple[float, int]]:
    """Interpretações possíveis (valor, casas decimais) de um número escrito em PT ou EN."""
    t = token.replace(" ", "").replace(" ", "").replace(" ", "")
    if not t or not re.search(r"\d", t):
        return []
    sign = -1 if t.startswith("-") else 1
    t = t.lstrip("+-")
    out = []
    if "," in t and "." in t:
        dec = "," if t.rfind(",") > t.rfind(".") else "."
        thou = "." if dec == "," else ","
        s = t.replace(thou, "").replace(dec, ".")
        out.append(s)
    elif "," in t or "." in t:
        sep = "," if "," in t else "."
        if re.fullmatch(rf"\d{{1,3}}(\{sep}\d{{3}})+", t):
            out.append(t.replace(sep, ""))           # separador de milhares
        if t.count(sep) == 1:
            out.append(t.replace(sep, "."))          # separador decimal
    else:
        out.append(t)
    res = []
    for s in out:
        try:
            res.append((sign * float(s), len(s.split(".")[1]) if "." in s else 0))
        except ValueError:
            pass
    return res


def numbers_in_text(text: str) -> list[tuple[str, list[tuple[float, int]], float]]:
    """(token, interpretações, multiplicador) para cada número no texto."""
    found = []
    for m in TOKEN.finditer(text or ""):
        tok = m.group(0).strip()
        rest = text[m.end():m.end() + 14]
        mult = next((k for rx, k in MULT if rx.match(rest)), 1.0)
        found.append((tok, parse(tok), mult))
    return found


def dossier_values(obj, acc: list | None = None) -> list[float]:
    acc = [] if acc is None else acc
    if isinstance(obj, bool) or obj is None:
        return acc
    if isinstance(obj, (int, float)):
        acc.append(float(obj))
    elif isinstance(obj, str):
        for _, interps, mult in numbers_in_text(obj):
            acc.extend(v * mult for v, _ in interps)
            acc.extend(v for v, _ in interps)
    elif isinstance(obj, dict):
        for v in obj.values():
            dossier_values(v, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            dossier_values(v, acc)
    return acc


def _matches(v: float, decimals: int, values: list[float]) -> bool:
    tol_round = 0.5 * 10 ** (-decimals) + 1e-9
    av = abs(v)
    for d in values:
        ad = abs(d)
        if abs(av - ad) <= max(tol_round, 0.011 * ad):
            return True
    return False


def check_numbers(texts: list[str], dossier) -> dict:
    values = dossier_values(dossier)
    checked, unverified = 0, []
    for text in texts:
        for tok, interps, mult in numbers_in_text(text):
            if not interps:
                continue
            v0, _ = interps[0]
            if (abs(v0) <= 31 and float(v0).is_integer()) or v0 in IGNORE or (1900 <= v0 <= 2100 and float(v0).is_integer()):
                continue  # contagens, dias, anos, janelas (SMA50, 52 semanas…)
            checked += 1
            ok = False
            for v, dec in interps:
                cands = [v, v * mult, v / 100, v * 100]
                if any(_matches(c, dec, values) for c in cands):
                    ok = True
                    break
            if not ok and tok not in unverified:
                unverified.append(tok)
    return {"checked": checked, "unverified": unverified}


SUMMARY_KEYS = ("symbol", "name", "sector", "industry", "market_cap_usd", "ipo_recente",
                "score", "label", "summary", "trend", "momentum", "consensus_score", "consensus_label", "n_analysts",
                "upside_mean_pct", "upside_median_pct", "dispersion_pct", "next_earnings", "days_to_earnings",
                "applicable", "signal_pct", "confidence", "health_score", "strength_score", "momentum_score",
                "valuation", "entry_quality", "overall", "structure", "rsi14", "returns_pct", "dist_high_52w_pct")


def compact(dossier: dict) -> dict:
    out = {}
    for k, v in (dossier or {}).items():
        v = as_dict(v)
        if isinstance(v, dict):
            out[k] = {kk: v[kk] for kk in SUMMARY_KEYS if kk in v}
            if isinstance(v.get("items"), list):
                out[k]["n_items"] = len(v["items"])
                out[k]["top"] = [i.get("title") for i in v["items"][:3] if isinstance(i, dict)]
            if isinstance(v.get("trend"), dict):
                out[k]["trend"] = v["trend"].get("label")
        else:
            out[k] = v
    return out


def run(decision, dossier, profile, version="v1", run_id=None):
    d, p = as_dict(decision), as_dict(profile)
    dossier = {k: as_dict(v) for k, v in (as_dict(dossier) or {}).items()}
    chk = check_numbers(list(d.get("reasons") or []) + list(d.get("risks") or []), dossier)
    warnings = []
    conf = float(d["confidence"])
    if chk["unverified"]:
        warnings.append(f"Números sem correspondência no dossier: {', '.join(chk['unverified'][:8])}")
        conf = max(0.0, conf - min(0.2, 0.05 * len(chk["unverified"])))
    gaps = sorted(k for k, v in dossier.items() if v is None)
    payload = compact(dossier)
    payload["debate"] = {"bull": d.get("bull_case"), "bear": d.get("bear_case")}
    payload["guard"] = chk
    return Synthesis(
        ticker=p["symbol"], rating=d["rating"], confidence=round(conf, 3), price=p.get("price"),
        currency=p.get("currency"), market=p.get("market"), version=version, horizon=d.get("horizon"),
        reasons=d.get("reasons") or [], risks=d.get("risks") or [], warnings=warnings, data_gaps=gaps,
        run_id=run_id, payload=payload,
    )
