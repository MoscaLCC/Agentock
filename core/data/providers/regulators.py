"""Reguladores: SEC EDGAR (EUA, inclui ADRs com 20-F) e OpenDART (Coreia). Endpoints verificados na Fase 2.

SEC exige User-Agent com contacto (SEC_USER_AGENT no .env). DART exige DART_API_KEY.
Os mapas ticker→CIK e ação→corp_code ficam em data/ (cache em disco, 7 e 30 dias).
"""
import html
import io
import json
import re
import time
import urllib.parse
import zipfile
from datetime import date, timedelta
from pathlib import Path

from ..http import ProviderError, fetch
from ..markets import base_code, market_of
from .base import Provider

DATA = Path(__file__).resolve().parents[3] / "data"


def _disk_cache(name: str, max_age_days: float, build):
    path = DATA / name
    if path.exists() and time.time() - path.stat().st_mtime < max_age_days * 86400:
        return json.loads(path.read_text(encoding="utf-8"))
    value = build()
    DATA.mkdir(exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return value


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n", html.unescape(text))).strip()


class SEC(Provider):
    name, env = "sec", ("SEC_USER_AGENT",)
    capabilities = frozenset({"filings", "subsidiaries", "sec_search", "lockup"})
    LOCKUP_RX = [
        re.compile(r"(\d{2,3})\s*days\s+after\s+the\s+date\s+of\s+(?:this|the\s+final)\s+prospectus", re.I),
        re.compile(r"lock[- ]?up\s+period[^.]{0,200}?(\d{2,3})\s+days", re.I),
        re.compile(r"period\s+of\s+(\d{2,3})\s+days\s+(?:after|following|from)", re.I),
    ]

    @classmethod
    def parse_lockup(cls, text: str) -> dict | None:
        from collections import Counter
        hits = []
        for rx in cls.LOCKUP_RX:
            for m in rx.finditer(text):
                d = int(m.group(1))
                if 30 <= d <= 730:
                    hits.append((d, text[max(0, m.start() - 120):m.end() + 60]))
        if not hits:
            return None
        days, _ = Counter(d for d, _ in hits).most_common(1)[0]
        snippet = next(s for d, s in hits if d == days)
        return {"days": days, "mentions": len(hits), "snippet": re.sub(r"\s+", " ", snippet)}

    def lockup(self, company: str):
        """Prazo de lock-up lido do prospeto final (424B4) de um IPO nos EUA."""
        docs = [d for d in self.sec_search(company, forms="424B4", days=730, limit=5) if d.get("url")]
        if not docs:
            return None
        text = _strip_html(self._get(docs[0]["url"], raw=True))
        found = self.parse_lockup(text)
        return found and {**found, "url": docs[0]["url"], "filing_date": docs[0]["date"], "filer": docs[0]["name"]}

    def _h(self):
        return {"User-Agent": self.key(), "Accept-Encoding": "identity"}

    def _get(self, url, raw=False):
        return fetch(url, self._h(), raw=raw, timeout=60)

    def _cik(self, symbol: str) -> int:
        tickers = _disk_cache("sec_tickers.json", 7, lambda: {
            v["ticker"]: v["cik_str"] for v in self._get("https://www.sec.gov/files/company_tickers.json").values()})
        cik = tickers.get(symbol.upper().replace(".", "-"))
        if not cik:
            raise ProviderError("notfound", f"{symbol} sem CIK na SEC")
        return cik

    def _recent(self, cik: int) -> dict:
        return self._get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")["filings"]["recent"]

    def filings(self, s, forms: str | None = None, limit: int = 20):
        if market_of(s) != "US":
            raise ProviderError("notfound", "SEC só para símbolos dos EUA (inclui ADRs)")
        cik = self._cik(s)
        rec = self._recent(cik)
        wanted = set(forms.split(",")) if forms else None
        out = []
        for i, form in enumerate(rec["form"]):
            if wanted and form not in wanted:
                continue
            acc = rec["accessionNumber"][i].replace("-", "")
            out.append({"form": form, "date": rec["filingDate"][i], "description": rec.get("primaryDocDescription", [""] * (i + 1))[i],
                        "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{rec['primaryDocument'][i]}"})
            if len(out) >= limit:
                break
        return out

    def subsidiaries(self, s, max_chars: int = 15000):
        """Exhibit 21 do último 10-K (ou Exhibit 8 do 20-F, para emitentes estrangeiros)."""
        if market_of(s) != "US":
            raise ProviderError("notfound", "SEC só para símbolos dos EUA (inclui ADRs)")
        cik = self._cik(s)
        rec = self._recent(cik)
        for form, pattern in (("10-K", r"ex(?:hibit)?[-_ ]?21"), ("20-F", r"ex(?:hibit)?[-_ ]?8")):
            if form not in rec["form"]:
                continue
            i = rec["form"].index(form)
            acc = rec["accessionNumber"][i].replace("-", "")
            items = self._get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json")["directory"]["item"]
            names = [it["name"] for it in items if re.search(pattern, it["name"].lower())
                     and it["name"].lower().endswith((".htm", ".html", ".txt"))]
            if not names:
                continue
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{sorted(names, key=len)[0]}"
            return {"form": form, "filing_date": rec["filingDate"][i], "url": url,
                    "text": _strip_html(self._get(url, raw=True))[:max_chars]}
        return None

    def sec_search(self, query: str, forms: str = "S-1,F-1,S-1/A,F-1/A,424B4", days: int = 365, limit: int = 10):
        """Pesquisa em texto integral do EDGAR (ex.: prospetos de IPO por nome da empresa)."""
        q = urllib.parse.urlencode({"q": f'"{query}"', "forms": forms, "dateRange": "custom",
                                    "startdt": (date.today() - timedelta(days=days)).isoformat(),
                                    "enddt": date.today().isoformat()})
        hits = (self._get(f"https://efts.sec.gov/LATEST/search-index?{q}").get("hits") or {}).get("hits") or []
        out = []
        for h in hits[:limit]:
            src = h.get("_source", {})
            adsh, _, filename = h.get("_id", "").partition(":")
            cik = (src.get("ciks") or [""])[0].lstrip("0")
            out.append({"name": (src.get("display_names") or [""])[0], "form": src.get("form"),
                        "date": src.get("file_date"),
                        "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh.replace('-', '')}/{filename}"
                        if cik and adsh and filename else None})
        return out


class DART(Provider):
    name, env = "dart", ("DART_API_KEY",)
    capabilities = frozenset({"filings"})
    BASE = "https://opendart.fss.or.kr/api/"

    def _corp_code(self, symbol: str) -> str:
        def build_map():
            import urllib.request
            req = urllib.request.Request(f"{self.BASE}corpCode.xml?crtfc_key={self.key()}",
                                         headers={"User-Agent": "Agentock/0.1"})
            with urllib.request.urlopen(req, timeout=180) as r:
                zf = zipfile.ZipFile(io.BytesIO(r.read()))
            xml = zf.read(zf.namelist()[0]).decode("utf-8")
            out = {}
            for block in re.findall(r"<list>(.*?)</list>", xml, re.S):  # um bloco por empresa
                corp = re.search(r"<corp_code>(\d+)</corp_code>", block)
                stock = re.search(r"<stock_code>\s*(\d{6})\s*</stock_code>", block)
                if corp and stock:
                    out[stock.group(1)] = corp.group(1)
            return out

        code = _disk_cache("dart_corp_codes.json", 30, build_map).get(base_code(symbol))
        if not code:
            raise ProviderError("notfound", f"{symbol} sem corp_code na DART")
        return code

    def filings(self, s, days: int = 90, limit: int = 20, forms: str | None = None):  # forms: só SEC
        if market_of(s) != "KR":
            raise ProviderError("notfound", "DART só para ações coreanas")
        q = urllib.parse.urlencode({"crtfc_key": self.key(), "corp_code": self._corp_code(s),
                                    "bgn_de": (date.today() - timedelta(days=days)).strftime("%Y%m%d"),
                                    "end_de": date.today().strftime("%Y%m%d"), "page_count": min(limit, 100)})
        d = fetch(f"{self.BASE}list.json?{q}")
        if d.get("status") not in ("000", "013"):  # 013 = sem dados
            raise ProviderError("error", f"DART {d.get('status')} {d.get('message')}")
        return [{"form": x.get("report_nm", "").strip(), "date": x.get("rcept_dt"), "description": x.get("flr_nm"),
                 "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={x.get('rcept_no')}"} for x in d.get("list", [])]
