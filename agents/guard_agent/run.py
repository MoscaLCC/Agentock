"""Guard: verifica os números e as datas da decisão contra o dossier e monta a Synthesis.

Os hooks só veem chamadas a ferramentas, não a resposta final — por isso esta verificação é um nó de script (D16).

Fase 10 (auditoria A2): a versão anterior aceitava ±1,1% e ×100/÷100 contra qualquer um dos ~1 700 valores do
dossier; num dossier real, números ao acaso passavam quase sempre. Agora:
  1. por campo — o juiz indica em `evidence` o caminho de cada número; o guard confere o número contra ESSE campo;
  2. por valor — sem caminho (ou caminho errado), procura no dossier inteiro, mas só com tolerância de
     arredondamento à precisão com que o número foi escrito ("12,5" casa com 12,4567; "13" não casa com 12,4567);
  3. ÷100 só quando o texto tem "%" (percentagem escrita vs fração no dossier);
  4. datas ("27 jan", "2026-11-03", "3 de novembro") têm de existir no dossier.
`by_path` são verificações fortes; `by_value` fracas (um inteiro pequeno casa por acaso com facilidade).
"""
import re

from core.schemas import Synthesis
from core.util import as_dict

SP = " \u00a0\u202f"   # espaço, espaço não separável e espaço fino (separadores de milhares)
# um espaço só faz parte do número como separador de milhares ("206 000"); "14,94 15,19" são dois números
TOKEN = re.compile(rf"(?<![\w.,])[-+\u2212]?(?:\d{{1,3}}(?:[{SP}]\d{{3}})+(?:[.,]\d+)?|\d[\d.,]*\d|\d)")
# multiplicadores: por extenso sem distinguir maiúsculas; letras soltas só em maiúscula ("5 M", "1,5B") — um "m"
# minúsculo pode ser metros ou meses. "mil milhões"/"mil M" têm de ser testados antes de "mil".
WORD_MULT = re.compile(r"\s*(biliões|bilião|trillions?|trilhões|mil\s+milhões|mil\s+m\b|billions?|milhões|milhão|"
                       r"millions?|mil\b|tn\b|bn\b|mn\b)", re.I)
LETTER_MULT = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3, "k": 1e3}
WORD_VALUE = [("mil milh", 1e9), ("mil m", 1e9), ("bili", 1e12), ("tril", 1e12), ("billion", 1e9), ("milh", 1e6),
              ("million", 1e6), ("mil", 1e3), ("tn", 1e12), ("bn", 1e9), ("mn", 1e6)]
IGNORE = {50.0, 52.0, 100.0, 200.0, 250.0, 252.0, 365.0}
# janelas de tempo habituais: "revisto em 90 dias", "a 180 dias" são o nome da janela, não um dado do dossier
TIME_WINDOWS = {30.0, 60.0, 90.0, 120.0, 180.0, 360.0}
TIME_UNIT = re.compile(r"\s*(dias?|sessões|sessão|semanas?|meses|mês|anos?|horas?)\b", re.I)
MONTHS = {m: i for i, names in enumerate((("jan", "janeiro"), ("fev", "fevereiro", "feb"), ("mar", "março"),
                                          ("abr", "abril", "apr"), ("mai", "maio", "may"), ("jun", "junho"),
                                          ("jul", "julho"), ("ago", "agosto", "aug"), ("set", "setembro", "sep"),
                                          ("out", "outubro", "oct"), ("nov", "novembro"), ("dez", "dezembro", "dec")), 1)
          for m in names}
_MONTH_RX = "|".join(sorted(MONTHS, key=len, reverse=True))
DATE_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")   # também "2026-11-03T14:00"
DATE_NUM = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
DATE_TXT = re.compile(rf"\b(\d{{1,2}})\s*(?:de\s+)?({_MONTH_RX})\b\.?(?:\s*(?:de\s+)?(\d{{4}}))?", re.I)


def parse(token: str) -> list[tuple[float, int]]:
    """Interpretações possíveis (valor, casas decimais) de um número escrito em PT ou EN."""
    t = re.sub(rf"[\s{SP}]", "", token).replace("\u2212", "-")
    if not t or not re.search(r"\d", t):
        return []
    sign = -1 if t.startswith("-") else 1
    t = t.lstrip("+-")
    out = []
    if "," in t and "." in t:
        dec = "," if t.rfind(",") > t.rfind(".") else "."
        thou = "." if dec == "," else ","
        out.append(t.replace(thou, "").replace(dec, "."))
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


def _suffix(rest: str) -> tuple[float, bool] | None:
    """(multiplicador, é percentagem) a partir do texto logo a seguir ao número; None se o número está colado a
    letras que não são uma unidade conhecida ("9M26", "10b5", "5G")."""
    pct = bool(re.match(r"\s*(%|por cento|p\.p\.|pontos percentuais)", rest))
    m = WORD_MULT.match(rest)
    if m:
        word = re.sub(r"\s+", " ", m.group(1).lower())
        return next(v for k, v in WORD_VALUE if word.startswith(k)), pct
    m = re.match(r"\s?([TBMKk])(?![\w])", rest)
    if m:
        return LETTER_MULT[m.group(1)], pct
    if re.match(r"x(?![\w])", rest):                 # múltiplo: "2,66x"
        return 1.0, pct
    if rest[:1].isalpha() or rest[:1] == "_":
        return None
    return 1.0, pct


def numbers_in_text(text: str) -> list[tuple[str, list[tuple[float, int]], float, bool]]:
    """(token, interpretações, multiplicador, é percentagem) para cada número no texto."""
    found = []
    for m in TOKEN.finditer(text or ""):
        tok = m.group(0).strip()
        rest = text[m.end():m.end() + 18]
        suf = _suffix(rest)
        if suf is None:
            continue
        interps = parse(tok)
        if interps and interps[0][0] in TIME_WINDOWS and TIME_UNIT.match(rest):
            continue
        found.append((tok, interps, suf[0], suf[1]))
    return found


def dates_in_text(text: str) -> list[tuple[str, int | None, int, int]]:
    """(texto, ano ou None, mês, dia) de cada data escrita."""
    out = []
    for m in DATE_ISO.finditer(text or ""):
        out.append((m.group(0), int(m.group(1)), int(m.group(2)), int(m.group(3))))
    for m in DATE_NUM.finditer(text or ""):
        out.append((m.group(0), int(m.group(3)), int(m.group(2)), int(m.group(1))))
    for m in DATE_TXT.finditer(text or ""):
        out.append((m.group(0).strip(), int(m.group(3)) if m.group(3) else None, MONTHS[m.group(2).lower()], int(m.group(1))))
    return [d for d in out if 1 <= d[2] <= 12 and 1 <= d[3] <= 31]


def leaves(obj, acc: list | None = None) -> list:
    """Todos os valores-folha (números e textos) de uma parte do dossier."""
    acc = [] if acc is None else acc
    if isinstance(obj, bool) or obj is None:
        return acc
    if isinstance(obj, (int, float, str)):
        acc.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            leaves(v, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            leaves(v, acc)
    return acc


def dossier_values(obj) -> list[float]:
    """Números do dossier: os campos numéricos e os números escritos dentro dos textos (com e sem multiplicador)."""
    vals: list[float] = []
    for leaf in leaves(obj):
        if isinstance(leaf, (int, float)):
            vals.append(float(leaf))
        else:
            for _, interps, mult, _pct in numbers_in_text(leaf):
                for v, _ in interps:
                    vals.append(v)
                    if mult != 1.0:
                        vals.append(v * mult)
    return vals


def dossier_dates(obj) -> set[tuple[int | None, int, int]]:
    out = set()
    for leaf in leaves(obj):
        if isinstance(leaf, str):
            out |= {(y, m, d) for _, y, m, d in dates_in_text(leaf)}
    return out


def resolve_path(dossier, path: str):
    """`a.b[2].c` → valor; None se o caminho não existir."""
    cur = dossier
    for part in re.findall(r"[^.\[\]]+|\[\d+\]", (path or "").strip()):
        if part.startswith("["):
            i = int(part[1:-1])
            if not isinstance(cur, (list, tuple)) or i >= len(cur):
                return None
            cur = cur[i]
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _tolerance(token: str, decimals: int) -> float:
    """Meia unidade da última casa escrita. Inteiros grandes arredondados ("475 600") toleram os zeros finais,
    até 3 algarismos significativos; "400" continua a exigir 400."""
    if decimals:
        return 0.5 * 10 ** (-decimals)
    digits = re.sub(r"\D", "", token)
    zeros = len(digits) - len(digits.rstrip("0"))
    return 0.5 * 10 ** min(zeros, max(0, len(digits) - 3)) if len(digits) >= 5 else 0.5


def _matches(token: str, interps, mult: float, pct: bool, values: list[float]) -> bool:
    for v, dec in interps:
        tol = _tolerance(token, dec)
        cands = [(v, tol, values)]
        if mult != 1.0:
            cands.append((v * mult, tol * mult, values))
        if pct:  # "55%" escrito, 0,55 no dossier — só contra frações, senão "4158%" casava com 41,58
            cands.append((v / 100, tol / 100, [d for d in values if abs(d) <= 1.5]))
        for c, t, pool in cands:
            ac = abs(c)
            if any(abs(ac - abs(d)) <= t + 1e-9 * max(1.0, ac) for d in pool):
                return True
    return False


def _skip(v0: float) -> bool:
    """Contagens, dias, anos e janelas (SMA50, 52 semanas…) não se conferem."""
    return (abs(v0) <= 31 and float(v0).is_integer()) or v0 in IGNORE or (1900 <= v0 <= 2100 and float(v0).is_integer())


def _norm_num(s: str) -> str:
    """Só algarismos e separadores: "+11,89%" e "−0,34" na evidência casam com "11,89" e "0,34" no texto."""
    return re.sub(r"[^\d.,]", "", s or "").strip(".,")


def check_numbers(texts: list[str], dossier, evidence: list | None = None) -> dict:
    values = dossier_values(dossier)
    paths: dict[str, list[str]] = {}
    for e in evidence or []:
        e = as_dict(e) or {}
        if e.get("number") and e.get("path"):
            paths.setdefault(_norm_num(str(e["number"])), []).append(str(e["path"]))
    checked = by_path = by_value = 0
    unverified: list[str] = []
    for text in texts:
        for tok, interps, mult, pct in numbers_in_text(text):
            if not interps or _skip(interps[0][0]):
                continue
            checked += 1
            at_path = [v for p in paths.get(_norm_num(tok), []) for v in dossier_values(resolve_path(dossier, p))]
            if at_path and _matches(tok, interps, mult, pct, at_path):
                by_path += 1
            elif _matches(tok, interps, mult, pct, values):
                by_value += 1
            elif tok not in unverified:
                unverified.append(tok)
    known = dossier_dates(dossier)
    dates_checked, dates_unverified = 0, []
    for text in texts:
        for raw, y, m, d in dates_in_text(text):
            dates_checked += 1
            if not any(km == m and kd == d and (y is None or ky is None or ky == y) for ky, km, kd in known) \
                    and raw not in dates_unverified:
                dates_unverified.append(raw)
    return {"checked": checked, "by_path": by_path, "by_value": by_value, "unverified": unverified,
            "dates_checked": dates_checked, "dates_unverified": dates_unverified}


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
        elif k != "gaps":
            out[k] = v
    return out


def _case_text(case) -> str | None:
    c = as_dict(case)
    if not c:
        return None
    if isinstance(c, str):
        return c
    lines = [f"{i}. {a}" for i, a in enumerate(c.get("arguments") or [], 1)]
    if c.get("concession"):
        lines.append(f"Ponto fraco: {c['concession']}")
    return "\n".join(lines) or None


def run(decision, dossier, profile, version="v1", run_id=None, bull=None, bear=None):
    d, p = as_dict(decision), as_dict(profile)
    dossier = {k: as_dict(v) for k, v in (as_dict(dossier) or {}).items()}
    sections = {k: v for k, v in dossier.items() if k != "gaps"}
    texts = list(d.get("reasons") or []) + list(d.get("risks") or []) + list(d.get("key_points") or []) + \
        [t for t in (d.get("headline"), d.get("bull_case"), d.get("bear_case")) if t]
    chk = check_numbers(texts, sections, d.get("evidence"))
    warnings = []
    conf = float(d["confidence"])
    bad = chk["unverified"] + chk["dates_unverified"]
    if chk["unverified"]:
        warnings.append(f"Números sem correspondência no dossier: {', '.join(chk['unverified'][:8])}")
    if chk["dates_unverified"]:
        warnings.append(f"Datas sem correspondência no dossier: {', '.join(chk['dates_unverified'][:5])}")
    if bad:
        conf = max(0.0, conf - min(0.2, 0.05 * len(bad)))
    if version == "v2" and (bull is None or bear is None):
        warnings.append("Debate incompleto: faltou o caso " + ("a favor" if bull is None else "contra")
                        + (" e o caso contra" if bull is None and bear is None else ""))
    gaps = sorted(k for k, v in sections.items() if v is None)
    payload = compact(sections)
    payload["debate"] = {"bull": d.get("bull_case"), "bear": d.get("bear_case"),
                         "bull_full": _case_text(bull), "bear_full": _case_text(bear)}
    payload["guard"] = chk
    return Synthesis(
        ticker=p["symbol"], rating=d["rating"], confidence=round(conf, 3), price=p.get("price"),
        currency=p.get("currency"), market=p.get("market"), version=version, horizon=d.get("horizon"),
        headline=d.get("headline"), key_points=d.get("key_points") or [],
        reasons=d.get("reasons") or [], risks=d.get("risks") or [], warnings=warnings, data_gaps=gaps,
        run_id=run_id, payload=payload,
    )
