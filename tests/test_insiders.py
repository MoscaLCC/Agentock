"""Insiders: parsers (SEC Form 4, DART) e regras do sinal (sem rede)."""
import unittest
from datetime import date

from agents.insiders_agent import run as ins
from core import sections
from core.data.insiders import (dart_role, expand_dart, parse_dart_document, parse_dart_elestock, parse_form4,
                                role_class)

TODAY = date(2026, 11, 15)

FORM4 = """<?xml version="1.0"?>
<ownershipDocument>
  <issuer><issuerCik>0000320193</issuerCik><issuerTradingSymbol>AAPL</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>COOK TIMOTHY D</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>1</isDirector><isOfficer>1</isOfficer>
      <officerTitle>Chief Executive Officer</officerTitle></reportingOwnerRelationship>
  </reportingOwner>
  <aff10b5One>0</aff10b5One>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-10-02</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>88,239</value></transactionShares>
        <transactionPricePerShare><value>333.26</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode></transactionAmounts>
      <postTransactionAmounts><sharesOwnedFollowingTransaction><value>3280295</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-10-01</value></transactionDate>
      <transactionCoding><transactionCode>F</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>330</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode></transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
  <footnotes><footnote id="F1">Sold pursuant to a Rule 10b5-1 trading plan adopted on May 1, 2026.</footnote></footnotes>
</ownershipDocument>"""

DART_DOC = """<SECTION-3><TITLE>다. 세부변동내역</TITLE><TABLE><TBODY>
<TR ACOPY="Y"><TU AUNIT="RPT_RSN" AUNITVALUE="35" ENG="Receipt of donation(+)">수증(+)</TU>
<TU AUNIT="MDF_DM" AUNITVALUE="20261112">2026년 11월 12일</TU><TU AUNIT="STR_KND" AUNITVALUE="1">보통주</TU>
<TE ACODE="BFR_STK_CNT">105,081,296</TE><TE ACODE="MDF_STK_CNT">11,158,000</TE><TE ACODE="AFR_STK_CNT">116,239,296</TE>
<TE ACODE="ACI_AMT2">-</TE><TE ACODE="RMK">증여자: 홍라희</TE><TU AUNIT="TRD_PLN_RD" AUNITVALUE="20261013">2026년 10월 13일</TU></TR>
<TR ACOPY="Y"><TU AUNIT="RPT_RSN" AUNITVALUE="02">장내매도(-)</TU>
<TU AUNIT="MDF_DM" AUNITVALUE="20261020">2026년 10월 20일</TU><TU AUNIT="STR_KND" AUNITVALUE="1">보통주</TU>
<TE ACODE="BFR_STK_CNT">5,000</TE><TE ACODE="MDF_STK_CNT">-1,000</TE><TE ACODE="AFR_STK_CNT">4,000</TE>
<TE ACODE="ACI_AMT2">250,500</TE><TE ACODE="RMK">-</TE><TU AUNIT="TRD_PLN_RD" AUNITVALUE="">-</TU></TR>
<TR><TD COLSPAN="3">합  계</TD><TE ACODE="BFR_STK_SUM">105,086,296</TE><TE ACODE="MDF_STK_SUM">11,157,000</TE></TR>
</TBODY></TABLE></SECTION-3>"""


def tx(code, name="A", d="2026-11-01", shares=1000, price=100.0, role_class="officer", planned=False, role=None):
    return {"date": d, "name": name, "role": role, "role_class": role_class, "code": code,
            "kind": {"P": "compra", "S": "venda"}.get(code, "outro"), "shares": shares, "price": price,
            "planned": planned}


class ParserTests(unittest.TestCase):
    def test_form4(self):
        txs = parse_form4(FORM4)
        self.assertEqual(len(txs), 2)
        s = txs[0]
        self.assertEqual((s["code"], s["kind"], s["shares"], s["price"]), ("S", "venda", 88239.0, 333.26))
        self.assertEqual((s["role_class"], s["issuer_cik"]), ("ceo", 320193))
        self.assertTrue(s["planned"])           # nota de rodapé "Rule 10b5-1"
        self.assertFalse(txs[1]["planned"])     # só vendas (S) podem ser planeadas
        self.assertEqual(txs[1]["kind"], "impostos")

    def test_role_class(self):
        self.assertEqual(role_class("Executive Chair"), "chair")
        self.assertEqual(role_class("Senior Vice President"), "officer")
        self.assertEqual(role_class("President and CEO"), "ceo")
        self.assertEqual(role_class(None, is_director=True), "director")
        self.assertEqual(role_class(None, is_ten=True), "owner10")

    def test_dart_roles(self):
        self.assertEqual(dart_role("대표이사 사장")[1], "ceo")
        self.assertEqual(dart_role("부사장")[1], "officer")     # não é 사장
        self.assertEqual(dart_role("부회장")[1], "officer")     # não é 회장
        self.assertEqual(dart_role("사외이사")[1], "director")
        self.assertEqual(dart_role("-"), ("—", "other"))

    def test_dart_summary_and_document(self):
        summary = parse_dart_elestock([
            {"rcept_dt": "2026-11-13", "rcept_no": "1", "repror": "이재용", "isu_exctv_ofcps": "회장",
             "isu_main_shrholdr": "사실상지배주주", "sp_stock_lmp_irds_cnt": "11,158,000", "sp_stock_lmp_cnt": "116,377,053"},
            {"rcept_dt": "2026-10-21", "rcept_no": "2", "repror": "X", "isu_exctv_ofcps": "상무",
             "isu_main_shrholdr": "-", "sp_stock_lmp_irds_cnt": "-1,000", "sp_stock_lmp_cnt": "4,000"},
            {"rcept_dt": "2025-01-01", "rcept_no": "3", "repror": "Y", "sp_stock_lmp_irds_cnt": "10"}], "2026-05-19")
        self.assertEqual([(t["code"], t["shares"]) for t in summary], [("INC", 11158000.0), ("DEC", 1000.0)])
        self.assertTrue(summary[0]["controlling"])
        rows = parse_dart_document(DART_DOC)
        self.assertEqual([(r["code"], r["shares"], r["acquired"]) for r in rows],
                         [("G", 11158000.0, True), ("S", 1000.0, False)])
        self.assertEqual((rows[0]["date"], rows[0]["plan_date"], rows[0]["price"]), ("2026-11-12", "2026-10-13", None))
        self.assertEqual(rows[1]["price"], 250500.0)
        full = expand_dart(summary[0], rows)
        self.assertEqual(full[0]["kind"], "doação recebida")
        self.assertEqual(full[0]["note"], "doador: 홍라희")
        self.assertIsNone(full[1]["note"])       # "-" não é nota
        self.assertEqual(full[0]["name"], "이재용")

    def test_dart_cached_code_is_recomputed(self):
        # cache antiga com 장외매수 → P: a compra fora de bolsa entre familiares não pode contar como compra
        old = [{"reason": "장외매수(+)", "code": "P", "date": "2026-10-12", "shares": 7667100.0, "acquired": True,
                "price": 250500.0, "note": "매도자: 홍라희", "plan_date": None}]
        t = expand_dart({"date": "2026-10-16", "name": "이재용"}, old)[0]
        self.assertEqual((t["code"], t["kind"], t["note"]), ("O", "fora de bolsa", "vendedor: 홍라희"))

    def test_sec_keeps_only_issuer_filings(self):
        from core.data.providers.regulators import SEC
        sec = SEC.__new__(SEC)
        sec._cik = lambda s: 1067983                                  # Berkshire
        sec._recent = lambda cik: {"form": ["4", "4"], "filingDate": ["2026-11-01", "2026-10-01"],
                                   "accessionNumber": ["a", "b"], "primaryDocument": ["x.xml", "y.xml"]}
        own = {**tx("P", d="2026-11-01"), "issuer_cik": 1067983}
        other = {**tx("S", d="2026-10-01"), "issuer_cik": 797468}    # a Berkshire a vender ações da OXY
        sec._form4 = lambda cik, acc, primary: [own] if acc == "a" else [other]
        self.assertEqual(sec.insider_transactions("BRK-B", days=180), [own])


class ScoreTests(unittest.TestCase):
    MC = 1_000_000_000.0  # market cap 1 000 M

    def an(self, txs, **kw):
        return ins.analyse(txs, 100.0, kw.pop("mc", self.MC), "sec", TODAY, "USD", **kw)

    def test_cluster_buy(self):
        out = self.an([tx("P", n, d) for n, d in (("A", "2026-10-01"), ("B", "2026-10-10"), ("C", "2026-10-25"))])
        self.assertEqual(out["score"], 2)
        self.assertIn("Compra em grupo", out["signals"][0])

    def test_three_buyers_spread_over_60_days_is_not_a_cluster(self):
        out = self.an([tx("P", n, d) for n, d in (("A", "2026-08-20"), ("B", "2026-09-20"), ("C", "2026-10-25"))])
        self.assertEqual(out["score"], 1)  # mas 300 mil = 0,03% da market cap → +1

    def test_senior_buy_threshold_in_usd(self):
        ceo = tx("P", "CEO", shares=1000, price=150.0, role_class="ceo", role="CEO")   # 150 mil
        self.assertEqual(self.an([ceo], mc=1e13)["score"], 1)
        # Coreia: 1 000 × 100 000 KRW = 100 M KRW ≈ 70 mil USD → abaixo dos 100 mil USD
        kr = tx("P", "CEO", shares=1000, price=100000.0, role_class="ceo")
        out = ins.analyse([kr], 100000.0, 1e15, "dart", TODAY, "KRW", usd_per_unit=0.0007, korea=True)
        self.assertEqual(out["score"], 0)
        self.assertIn("peso baixo", out["signals"][0])

    def test_planned_sales_are_weak(self):
        out = self.an([tx("S", "A", shares=100000, planned=True)])  # 10 M = 1% da market cap, mas planeada
        self.assertEqual(out["score"], 0)
        self.assertIn("todas em plano 10b5-1", out["signals"][0])

    def test_discretionary_sales(self):
        self.assertEqual(self.an([tx("S", "A", shares=60000)])["score"], -2)            # 0,6% da market cap
        self.assertEqual(self.an([tx("S", "A", shares=15000)])["score"], -1)            # 0,15%
        self.assertEqual(self.an([tx("S", n, shares=10) for n in "ABC"])["score"], -1)  # 3 vendedores
        self.assertEqual(self.an([tx("S", "A", shares=10)])["score"], 0)

    def test_buys_and_sells_offset(self):
        out = self.an([tx("P", "CEO", shares=2000, role_class="ceo"), *[tx("S", n, shares=10) for n in "ABC"]])
        self.assertEqual(out["score"], 0)
        self.assertEqual(len(out["signals"]), 2)

    def test_routine_codes_do_not_count(self):
        out = self.an([tx("A", "A", shares=10**6), tx("M", "B", shares=10**6), tx("G", "C", shares=10**6),
                       tx("F", "D", shares=10**6)])
        self.assertEqual(out["score"], 0)
        self.assertEqual(out["routine_180d"]["atribuições"], 1)
        self.assertIn("Sem compras nem vendas", out["signals"][0])

    def test_old_transactions_outside_window(self):
        out = self.an([tx("S", "A", d="2026-07-01", shares=60000)])  # > 90 dias
        self.assertEqual(out["score"], 0)
        self.assertEqual(out["windows"]["180"]["sells"], 1)

    def test_korea_plan_wording_and_unread(self):
        txs = [tx("S", "A", shares=10, planned=True), {**tx("INC", "B"), "code": "INC"}]
        out = ins.analyse(txs, 100.0, self.MC, "dart", TODAY, "KRW", korea=True)
        self.assertIn("com pré-aviso", out["signals"][0])
        self.assertIn("1 relatórios pequenos", out["signals"][-1])

    def test_finnhub_fallback_is_capped(self):
        out = ins.analyse([tx("S", "A", shares=60000)], 100.0, self.MC, "finnhub", TODAY, "USD")  # seria −2
        self.assertEqual(out["score"], -1)
        self.assertIn("Finnhub", out["signals"][-1])

    def test_unavailable_market(self):
        out = ins.run({"symbol": "0700.HK", "market": "HK"})
        self.assertFalse(out["available"])
        self.assertIsNone(out["score"])


class SectionTests(unittest.TestCase):
    def data(self, out):
        return {"run": {"ticker": "AAPL"}, "outputs": {"insiders": out}}

    def test_table_fits_phone(self):
        out = ins.analyse([tx("S", "COOK TIMOTHY D", shares=123456, planned=True, role="CEO"),
                           tx("P", "B", shares=999999)], 100.0, 1e12, "sec", TODAY, "USD")
        txt = sections.sec_insiders(self.data(out))
        pre = txt.split("<pre>")[1].split("</pre>")[0]
        self.assertTrue(all(len(line) <= 37 for line in pre.split("\n")), pre)
        self.assertIn("Cook Timothy D", txt)
        self.assertIn("plano 10b5-1", txt)

    def test_unavailable(self):
        txt = sections.sec_insiders(self.data({"available": False, "reason": "sem fonte"}))
        self.assertIn("Sem dados de insiders: sem fonte", txt)

    def test_short_money(self):
        self.assertEqual(sections.short_money(97_482_332), "97 M")
        self.assertEqual(sections.short_money(1.36e9), "1,4 mM")
        self.assertEqual(sections.short_money(2.3e12), "2,3 B")
        self.assertEqual(sections.short_money(-4_200_000), "-4,2 M")


if __name__ == "__main__":
    unittest.main()
