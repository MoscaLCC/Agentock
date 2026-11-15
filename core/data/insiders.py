"""Parsers de transações de insiders (funções puras, testáveis sem rede).

Formato normalizado de cada transação:
  {date, name, role, role_class, code, kind, shares, price, acquired, planned, owned_after, source, ...}
  role_class: ceo | cfo | chair | president | officer | director | owner10 | other
  code (SEC): P compra em bolsa · S venda em bolsa · A atribuição · M/X exercício · C conversão · F impostos ·
              G doação · D devolução · J/I outro · W herança.
  DART: o mesmo código, a partir do motivo do documento (장내매수 → P, 장내매도 → S, 수증/증여 → G, 상속 → W,
        자사주상여금 → A, 주식매수선택권 → M); INC / DEC quando o documento não foi lido (motivo desconhecido).
"""
import re

SEC_CODES = {"P": "compra", "S": "venda", "A": "atribuição", "M": "exercício", "X": "exercício", "C": "conversão",
             "F": "impostos", "G": "doação", "D": "devolução", "J": "outro", "W": "herança", "I": "outro",
             "O": "fora de bolsa"}  # O: só DART — transferência negociada fora de bolsa (ex.: entre familiares)
SENIOR = {"ceo", "cfo", "chair", "president"}


def _num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def role_class(title: str | None, is_director=False, is_officer=False, is_ten=False) -> str:
    t = (title or "").lower()
    if re.search(r"chief executive|\bceo\b", t):
        return "ceo"
    if re.search(r"chief financial|\bcfo\b", t):
        return "cfo"
    if "chair" in t:
        return "chair"
    if re.search(r"(?<!vice )president", t):
        return "president"
    if is_officer or title:
        return "officer"
    if is_director:
        return "director"
    return "owner10" if is_ten else "other"


def parse_form4(xml_text: str) -> list[dict]:
    """Transações não derivadas de um Form 4 da SEC."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml_text)

    def tx(el, path):
        node = el.find(path) if el is not None else None
        return node.text.strip() if node is not None and node.text else None

    owners = root.findall("reportingOwner")
    names = [tx(o, "reportingOwnerId/rptOwnerName") for o in owners]
    rel = owners[0].find("reportingOwnerRelationship") if owners else None

    def flag(path):
        return (tx(rel, path) or "").lower() in ("1", "true")

    issuer_cik = _num(tx(root, "issuer/issuerCik"))  # a declarante pode ser acionista noutra empresa
    title = tx(rel, "officerTitle")
    planned = (tx(root, "aff10b5One") or "").lower() in ("1", "true") or \
        any("10b5-1" in (f.text or "") for f in root.iter("footnote"))
    rc = role_class(title, flag("isDirector"), flag("isOfficer"), flag("isTenPercentOwner"))
    role = title or ("Administrador" if flag("isDirector") else "Acionista >10%" if flag("isTenPercentOwner") else None)
    out = []
    for t in root.iter("nonDerivativeTransaction"):
        code = tx(t, "transactionCoding/transactionCode")
        price = _num(tx(t, "transactionAmounts/transactionPricePerShare/value"))
        out.append({"date": tx(t, "transactionDate/value"), "name": " / ".join(n for n in names if n),
                    "role": role, "role_class": rc, "code": code, "kind": SEC_CODES.get(code, "outro"),
                    "shares": _num(tx(t, "transactionAmounts/transactionShares/value")) or 0.0,
                    "price": price or None,
                    "acquired": tx(t, "transactionAmounts/transactionAcquiredDisposedCode/value") == "A",
                    "planned": planned and code == "S",
                    "owned_after": _num(tx(t, "postTransactionAmounts/sharesOwnedFollowingTransaction/value")),
                    "issuer_cik": int(issuer_cik) if issuer_cik else None, "source": "sec"})
    return out


# ordem importa: 대표이사 antes de 이사, 부회장 antes de 회장, 부사장 antes de 사장
DART_ROLES = [("대표이사", "CEO", "ceo"), ("부회장", "Vice-chairman", "officer"), ("회장", "Chairman", "chair"),
              ("부사장", "Vice-presidente executivo", "officer"), ("사장", "Presidente executivo", "president"),
              ("전무", "Diretor sénior", "officer"), ("상무", "Diretor", "officer"),
              ("사외이사", "Administrador independente", "director"), ("감사", "Auditor", "other"),
              ("이사", "Administrador", "director"), ("담당", "Responsável executivo", "officer"),
              ("본부장", "Diretor de divisão", "officer"), ("부문장", "Diretor de divisão", "officer"),
              ("센터장", "Diretor de centro", "officer"), ("고문", "Consultor", "other")]


def dart_role(ofcps: str | None) -> tuple[str, str]:
    o = (ofcps or "").strip()
    for key, label, cls in DART_ROLES:
        if key in o:
            return label, cls
    return ("Executivo", "officer") if o and o != "-" else ("—", "other")


def parse_dart_elestock(rows: list[dict], cutoff: str) -> list[dict]:
    """Resumo dos relatórios 임원ㆍ주요주주 소유 (OpenDART elestock): variação líquida por relatório, sem motivo
    nem preço (code INC/DEC). O motivo vem do documento do relatório (parse_dart_document + expand_dart)."""
    out = []
    for x in rows:
        if (x.get("rcept_dt") or "") < cutoff:
            continue
        chg = _num(x.get("sp_stock_lmp_irds_cnt"))
        if not chg:
            continue
        role, cls = dart_role(x.get("isu_exctv_ofcps"))
        holder = (x.get("isu_main_shrholdr") or "").strip()
        out.append({"date": x["rcept_dt"], "name": x.get("repror"), "role": role, "role_class": cls,
                    "code": "INC" if chg > 0 else "DEC", "kind": "aumento" if chg > 0 else "redução",
                    "shares": abs(chg), "price": None, "acquired": chg > 0, "planned": False,
                    "owned_after": _num(x.get("sp_stock_lmp_cnt")), "rcept_no": x.get("rcept_no"),
                    "registered": x.get("isu_exctv_rgist_at") == "등기임원",
                    "controlling": "지배주주" in holder, "major_holder": holder not in ("", "-"), "source": "dart"})
    return out


# motivo da variação (rótulo coreano do documento) → código equivalente ao do Form 4. A ordem importa.
DART_REASONS = [("장내매수", "P"), ("시간외매수", "P"), ("장외매수", "O"),
                ("장내매도", "S"), ("시간외매도", "S"), ("장외매도", "O"),
                ("수증", "G"), ("증여", "G"), ("상속", "W"),
                ("상여", "A"), ("성과", "A"), ("양도제한", "A"),
                ("주식매수선택권", "M"), ("스톡옵션", "M"), ("전환", "C")]


def dart_reason_code(label: str) -> str:
    for key, code in DART_REASONS:
        if key in (label or ""):
            return code
    return "J"  # 신규선임, 신탁, 기타…: não é opinião sobre o preço


def _iso(yyyymmdd: str | None) -> str | None:
    d = (yyyymmdd or "").strip()
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 and d.isdigit() else None


def parse_dart_document(xml_text: str) -> list[dict]:
    """Tabela 세부변동내역 do documento de um relatório elestock: uma linha por variação, com motivo, data,
    preço, nota e data do pré-aviso de negociação (거래계획보고, regime coreano desde 2024)."""
    rows = []
    for tr in re.findall(r"<TR[^>]*>(.*?)</TR>", xml_text, re.S):
        tags = {}
        for attrs, text in re.findall(r"<T[UED]\b([^>]*)>([^<]*)<", tr):
            key = re.search(r'(?:AUNIT|ACODE)="([^"]+)"', attrs)
            if key:
                val = re.search(r'AUNITVALUE="([^"]*)"', attrs)
                tags[key.group(1)] = (text.strip(), val.group(1) if val else None)
        if "RPT_RSN" not in tags or "MDF_STK_CNT" not in tags:
            continue
        label = tags["RPT_RSN"][0]
        chg = _num(tags["MDF_STK_CNT"][0]) or 0.0
        acquired = "(+)" in label if ("(+)" in label or "(-)" in label) else chg > 0
        price = _num(tags.get("ACI_AMT2", ("",))[0])
        rows.append({"reason": label, "code": dart_reason_code(label), "date": _iso(tags.get("MDF_DM", ("", ""))[1]),
                     "shares": abs(chg), "acquired": acquired, "price": price or None,
                     "note": tags.get("RMK", ("",))[0] or None,
                     "plan_date": _iso(tags.get("TRD_PLN_RD", ("", ""))[1])})
    return rows


DART_NOTE = [("증여자", "doador"), ("수증자", "beneficiário"), ("피상속인", "falecido"), ("매도자", "vendedor"),
             ("매수자", "comprador"), ("기보유분", "ações já detidas")]


def expand_dart(summary: dict, rows: list[dict]) -> list[dict]:
    """Substitui a linha-resumo de um relatório pelas variações detalhadas do documento."""
    out = []
    for r in rows:
        r = {**r, "code": dart_reason_code(r["reason"])}  # recalculado: a cache em disco guarda o motivo
        kind = SEC_CODES.get(r["code"], "outro")
        if r["code"] == "G" and r["acquired"]:
            kind = "doação recebida"
        note = r.get("note") if r.get("note") not in (None, "-") else None
        for kr, pt in DART_NOTE:
            note = note.replace(kr, pt) if note else note
        out.append({**summary, "date": r["date"] or summary["date"], "code": r["code"], "kind": kind,
                    "shares": r["shares"], "price": r["price"], "acquired": r["acquired"],
                    "planned": bool(r.get("plan_date")) and r["code"] == "S", "reason": r["reason"], "note": note})
    return out
