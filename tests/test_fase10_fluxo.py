"""Fase 10 — fluxo reestruturado: guard por campo, notícias numa só recolha, sentimento por código, dossier
compacto, debate em nós paralelos, hooks de segurança e cache por conteúdo."""
import asyncio
import importlib.util
import json
import random
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core import dossier, hooks, news, sentiment
from core.orchestrator import deps, layers, load_flow
from core.runner import cache_key
from core.spec import load_agent

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)


def load(agent: str):
    spec = importlib.util.spec_from_file_location(f"_t10f_{agent}", ROOT / "agents" / agent / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ago(**kw) -> str:
    return news.iso(NOW - timedelta(**kw))


# ---------------------------------------------------------------------------------------------- guard
class GuardTests(unittest.TestCase):
    def setUp(self):
        self.g = load("guard_agent")

    def check(self, text, dossier_, evidence=None):
        return self.g.check_numbers([text], dossier_, evidence)

    def test_scaled_number_is_not_accepted(self):
        """A2 — "266" passava por ser 2,66 × 100 com tolerância ±0,5."""
        self.assertEqual(self.check("P/E forward de 266", {"forward_pe": 2.66})["unverified"], ["266"])
        self.assertEqual(self.check("ROE de 4158%", {"roe_pct": 41.58})["unverified"], ["4158"])
        self.assertEqual(self.check("P/E forward de 2,66", {"forward_pe": 2.66})["unverified"], [])

    def test_tolerance_is_the_rounding_of_what_was_written(self):
        d = {"upside": 12.4567, "rsi": 44.4}
        self.assertEqual(self.check("potencial de 12,5%", d)["unverified"], [])
        self.assertEqual(self.check("potencial de 12,46%", d)["unverified"], [])
        self.assertEqual(self.check("potencial de 12,9%", d)["unverified"], ["12,9"])
        self.assertEqual(self.check("RSI de 44", d)["unverified"], [])
        self.assertEqual(self.check("RSI de 45", d)["unverified"], ["45"])        # antes: ±1,1% aceitava

    def test_percent_written_vs_fraction_in_dossier(self):
        self.assertEqual(self.check("confiança de 55%", {"confidence": 0.55})["unverified"], [])
        self.assertEqual(self.check("um rácio de 55", {"confidence": 0.55})["unverified"], ["55"])   # sem %: não divide

    def test_multipliers(self):
        """C1 — "mi" casava com "mil" (×1e6) e "tri" com "trimestres"."""
        d = {"mcap": 1.5e9, "price": 206000.0, "rev": 94.9e9, "cap": 5.177e12, "fine": 220e6}
        for text in ("capitalização de 1,5 mil M USD", "preço de 206 mil KRW", "receitas de 94,9 mil milhões",
                     "vale 5,18 biliões", "market cap de 1.5B", "multa de 220 M USD", "preço de 206 000 KRW",
                     "preço de 206.000 KRW"):
            out = self.check(text, d)
            self.assertEqual((out["checked"], out["unverified"]), (1, []), text)
        self.assertEqual(self.check("caiu 47 trimestres", {"x": 47e12})["unverified"], ["47"])

    def test_large_rounded_integers(self):
        self.assertEqual(self.check("alvo médio de 475 600 KRW", {"mean": 475629.0})["unverified"], [])
        self.assertEqual(self.check("alvo médio de 476 000 KRW", {"mean": 475629.0})["unverified"], [])
        self.assertEqual(self.check("alvo médio de 480 000 KRW", {"mean": 475629.0})["unverified"], ["480 000"])
        self.assertEqual(self.check("alvo de 400 USD", {"mean": 437.0})["unverified"], ["400"])   # 3 dígitos: exato

    def test_ignores_counts_years_windows_and_period_codes(self):
        out = self.check("3 analistas subiram o rating em 2026; SMA de 200 dias, máximo de 52 semanas, 9M26, 10b5-1",
                         {"x": 1.0})
        self.assertEqual(out["checked"], 0)

    def test_time_windows_are_not_data(self):
        """9988.HK, 2026-11-15: "nenhum alvo foi revisto em 90 dias" custou 0,05 de confiança sem razão."""
        d = {"price": 90.55, "days_to_earnings": 74}
        self.assertEqual(self.check("nenhum alvo foi revisto em 90 dias; vendas a 180 dias", d)["checked"], 0)
        self.assertEqual(self.check("resultados daqui a 74 dias", d)["unverified"], [])     # um dado: confere-se
        self.assertEqual(self.check("resultados daqui a 75 dias", d)["unverified"], ["75"])
        self.assertEqual(self.check("preço de 90 HKD", d)["unverified"], ["90"])            # 90,55 não é 90

    def test_two_numbers_separated_by_a_space_are_two_numbers(self):
        out = self.check("zona de compra entre 14,94 15,19", {"lo": 14.94, "hi": 15.19})
        self.assertEqual((out["checked"], out["unverified"]), (2, []))

    def test_evidence_path_is_a_strong_check(self):
        d = {"fundamental_data": {"valuation": {"forward_pe": 2.66}}, "technical": {"signals": ["RSI14 de 42,03"]},
             "other": {"x": 2.66}}
        ev = [{"number": "2,66", "path": "fundamental_data.valuation.forward_pe"},
              {"number": "42,03", "path": "technical.signals[0]"}]
        out = self.check("P/E de 2,66 e RSI de 42,03", d, ev)
        self.assertEqual((out["checked"], out["by_path"], out["by_value"], out["unverified"]), (2, 2, 0, []))
        wrong = [{"number": "2,66", "path": "technical.signals[0]"}]            # caminho errado: fica verificação fraca
        out = self.check("P/E de 2,66", d, wrong)
        self.assertEqual((out["by_path"], out["by_value"], out["unverified"]), (0, 1, []))
        out = self.check("P/E de 3,10", d, [{"number": "3,10", "path": "fundamental_data.valuation.forward_pe"}])
        self.assertEqual(out["unverified"], ["3,10"])                            # o campo citado não tem esse número

    def test_dates_must_exist_in_the_dossier(self):
        d = {"calendar": {"next_earnings": "2027-01-27"}, "news": {"items": [{"at": "2026-11-03T14:00"}]}}
        ok = self.check("Resultados a 27 jan; a 3 de novembro saiu o guidance; 27/01/2027", d)
        self.assertEqual((ok["dates_checked"], ok["dates_unverified"]), (3, []))
        bad = self.check("Resultados a 29/10/2026 e a 28 de janeiro", d)
        self.assertEqual(bad["dates_unverified"], ["29/10/2026", "28 de janeiro"])

    def test_random_numbers_are_mostly_rejected(self):
        """Num dossier com ~400 valores, números ao acaso com casas decimais passavam 64–79% das vezes."""
        rng = random.Random(7)
        d = {f"k{i}": round(rng.uniform(0, 100), 2) for i in range(200)}
        d.update({f"p{i}": round(rng.uniform(100, 500000), 1) for i in range(200)})
        trials = [f"{rng.uniform(32, 999):.2f}".replace(".", ",") for _ in range(400)]
        accepted = sum(not self.check(f"valor de {t}", d)["unverified"] for t in trials)
        self.assertLess(accepted / len(trials), 0.05)

    def test_synthesis_checks_debate_cases_and_penalises(self):
        d = {"profile": {"price": 356.27}, "indicators": {"rsi14": 71.3}, "sentiment": None, "gaps": ["sentiment"]}
        decision = {"rating": "buy", "confidence": 0.7, "horizon": "6-12 meses", "reasons": ["RSI de 71,3"],
                    "risks": ["Valorização exigente"], "bull_case": "Margem de 47,8%", "bear_case": "RSI em 71,3",
                    "evidence": [{"number": "71,3", "path": "indicators.rsi14"}]}
        s = self.g.run(decision, d, {"symbol": "AAPL", "price": 356.27, "currency": "USD", "market": "US"}, "v2", "r1",
                       bull={"arguments": ["a"], "concession": "c"}, bear=None)
        self.assertAlmostEqual(s.confidence, 0.65)                               # 47,8 não existe no dossier
        self.assertEqual(s.data_gaps, ["sentiment"])
        self.assertEqual(s.payload["guard"]["by_path"], 2)
        self.assertIn("47,8", s.warnings[0])
        self.assertTrue(any("Debate incompleto" in w for w in s.warnings))
        self.assertIn("1. a", s.payload["debate"]["bull_full"])


# ---------------------------------------------------------------------------------------------- notícias
class NewsTests(unittest.TestCase):
    RAW = [
        {"title": "Samsung in talks to buy Modine", "url": "https://x.com/a?utm=1", "published_at": ago(hours=2), "source": "X"},
        {"title": "Samsung in talks to buy Modine - report", "url": "https://y.com/b", "published_at": ago(hours=3)},
        {"title": "Samsung HBM4E mass production", "url": "https://z.com/c", "published_at": ago(hours=30), "summary": "s" * 500},
        {"title": "Quarterly results beat", "url": "https://z.com/d", "published_at": ago(days=12)},
        {"title": "Too old", "url": "https://z.com/e", "published_at": ago(days=45)},
        {"title": "No date", "url": "https://z.com/f", "published_at": None},
    ]

    def test_collect_dedupes_windows_and_gives_stable_ids(self):
        feed = news.collect(self.RAW, NOW, symbol="005930.KS", company="Samsung")
        self.assertEqual([i["w"] for i in feed["items"]], ["4h", "7d", "30d"])
        self.assertEqual(feed["counts"], {"4h": 1, "24h": 0, "7d": 1, "30d": 1})
        self.assertEqual(feed["gaps"], ["sem itens das APIs em 24h"])
        self.assertEqual(len(feed["items"][1]["snippet"]), 240)
        again = news.collect(list(reversed(self.RAW)), NOW + timedelta(minutes=10))
        self.assertEqual([i["id"] for i in feed["items"]], [i["id"] for i in again["items"]])   # ids não dependem da ordem
        self.assertEqual(news.item_id("https://www.x.com/a?utm=2", None), feed["items"][0]["id"])

    def test_parse_ts_formats(self):
        self.assertEqual(news.parse_ts("2026-11-14T17:03:53Z"), datetime(2026, 11, 14, 17, 3, 53, tzinfo=timezone.utc))
        self.assertEqual(news.parse_ts("2026-11-14T18:03:53+01:00").hour, 17)
        self.assertEqual(news.parse_ts(1794675833).year, 2026)
        self.assertEqual(news.parse_ts("Sat, 14 Nov 2026 17:03:53 GMT").day, 14)
        self.assertIsNone(news.parse_ts("ontem"))

    def test_merge_triages_drops_and_keeps_fresh_headlines(self):
        feed = news.collect(self.RAW, NOW)
        ids = [i["id"] for i in feed["items"]]
        scan = {"scanned_at": ago(hours=1), "annotations": [
            {"id": ids[1], "relevance": 4, "tone": "Positivo", "category": "product", "summary": "Produção em massa."}],
            "web_items": [{"title": "DART: aquisição aprovada", "source": "DART", "url": "https://dart.fss.or.kr/1",
                           "published_at": ago(days=20), "time_confirmed": True, "relevance": 5, "tone": "positivo",
                           "category": "m&a", "summary": "Aprovada."},
                          {"title": "Sem data", "url": "https://q.com", "published_at": "há dias", "relevance": 5}]}
        fresh = {"title": "Breaking: CEO steps down", "url": "https://n.com/1", "published_at": ago(minutes=10)}
        feed2 = news.collect([fresh] + self.RAW, NOW)
        out = news.merge(feed2, scan, NOW)
        by_title = {i["title"]: i for i in out["items"]}
        self.assertEqual(by_title["Samsung HBM4E mass production"]["tone"], "positivo")
        self.assertTrue(by_title["Samsung HBM4E mass production"]["triaged"])
        self.assertNotIn("Samsung in talks to buy Modine", by_title)             # visto pelo LLM e não anotado: sai
        self.assertNotIn("Quarterly results beat", by_title)
        self.assertFalse(by_title["Breaking: CEO steps down"]["triaged"])        # saiu depois da triagem: entra já
        self.assertEqual(by_title["DART: aquisição aprovada"]["w"], "30d")
        self.assertNotIn("Sem data", by_title)
        self.assertEqual(out["untriaged"], 1)
        self.assertEqual(out["per_window"], {"4h": 1, "24h": 0, "7d": 1, "30d": 1})

    def test_merge_without_scan_serves_untriaged_feed(self):
        out = news.merge(news.collect(self.RAW, NOW), None, NOW)
        self.assertEqual(out["untriaged"], 3)
        self.assertIn("sem triagem", out["note"])

    def test_windows_are_recomputed_at_read_time_and_capped(self):
        import hashlib
        raw = [{"title": hashlib.md5(str(i).encode()).hexdigest(), "url": f"https://a.com/{i}",
                "published_at": ago(hours=3)} for i in range(30)]                # 30 títulos sem nada em comum
        feed = news.collect(raw, NOW)
        scan = {"scanned_at": ago(minutes=1), "annotations": [
            {"id": it["id"], "relevance": 1 + i % 5, "tone": "neutro", "category": "other", "summary": "x"}
            for i, it in enumerate(feed["items"])]}
        out = news.merge(feed, scan, NOW)
        self.assertEqual(out["per_window"]["4h"], news.CAPS["4h"])
        self.assertEqual(out["items"][0]["relevance"], 5)                        # os mais relevantes primeiro
        later = news.merge(feed, scan, NOW + timedelta(hours=6))                 # 6 h depois: já não são "4h"
        self.assertEqual((later["per_window"]["4h"], later["per_window"]["24h"]), (0, news.CAPS["24h"]))

    def test_legacy_digest_merges_old_windows_without_repeats(self):
        item = {"title": "A", "url": "https://a.com/1", "published_at": ago(hours=1), "relevance": 5, "tone": "negativo",
                "category": "legal", "summary": "s", "source": "X"}
        dig = news.legacy_digest({"4h": {"items": [item]}, "24h": {"items": [item]}, "7d": {"items": []}, "30d": None})
        self.assertEqual((len(dig["items"]), dig["items"][0]["w"]), (1, "4h"))
        self.assertIsNone(news.legacy_digest({"4h": None, "24h": None, "7d": None, "30d": None}))


# ---------------------------------------------------------------------------------------------- sentimento
class SentimentTests(unittest.TestCase):
    def item(self, tone, rel, w="24h"):
        return {"tone": tone, "relevance": rel, "w": w, "title": f"{tone}{rel}{w}", "summary": "resumo", "triaged": True}

    def test_news_score_follows_the_rubric(self):
        # pesos 5→3, 4→2, 3→1: (−3 + 2 + 0) ÷ (3 + 2 + 1) = −0,1667 (o teto de 35% por item: 3 → 2,1 ⇒ −0,1/5,1)
        score, counts = sentiment.news_score([self.item("negativo", 5), self.item("positivo", 4), self.item("neutro", 3)])
        self.assertAlmostEqual(score, (-2.1 + 2) / (2.1 + 2 + 1), places=4)
        self.assertEqual((counts["positivo"], counts["negativo"], counts["neutro"]), (1, 1, 1))
        self.assertEqual(sentiment.news_score([])[0], None)
        self.assertEqual(sentiment.news_score([{"tone": "positivo", "relevance": None}])[0], None)   # por triar

    def test_single_item_cannot_dominate(self):
        many = [self.item("positivo", 2) for _ in range(6)] + [self.item("negativo", 5)]
        score, _ = sentiment.news_score(many)
        self.assertGreater(score, -0.1)                                         # sem teto seria (3 − 3) / 6 = 0 … ok
        two = sentiment.news_score([self.item("negativo", 5), self.item("positivo", 1)])[0]
        self.assertAlmostEqual(two, (-3 + 0.25) / 3.25)                         # com < 3 itens não há teto

    def test_aggregate_weights_and_redistribution(self):
        analysts = {"consensus_score": 1.3, "n_analysts": 69, "trend": 0.04,
                    "counts": {"strong_buy": 25, "buy": 41, "hold": 2, "sell": 1, "strong_sell": 0},
                    "changes_90d": {"up": 0, "down": 10, "net": -10}}
        out = sentiment.compute({"items": [self.item("negativo", 5), self.item("negativo", 4)]}, analysts,
                                {"available": True, "score": -1, "signals": ["3 vendedores em 30 dias"]})
        self.assertEqual(out["news"]["score"], -1.0)
        self.assertEqual(out["analysts"]["score"], 0.55)                        # 1,3 ÷ 2 − 0,1 (10 descidas)
        self.assertEqual(out["insiders"]["score"], -0.5)
        self.assertAlmostEqual(out["overall_score"], round(-1 * 0.5 + 0.55 * 0.35 - 0.5 * 0.15, 2))
        self.assertEqual((out["label"], out["score"]), ("negativo", -1))
        no_ins = sentiment.compute({"items": [self.item("positivo", 5)]}, analysts, {"available": False, "reason": "sem fonte"})
        self.assertIsNone(no_ins["insiders"]["score"])
        self.assertAlmostEqual(no_ins["overall_score"], round((1 * 0.5 + 0.55 * 0.35) / 0.85, 2))
        self.assertIn("sem fonte", no_ins["insiders"]["basis"])

    def test_trend_compares_short_and_long_windows(self):
        items = [self.item("positivo", 4, "4h"), self.item("positivo", 3, "24h"), self.item("negativo", 4, "7d"),
                 self.item("negativo", 3, "30d")]
        self.assertEqual(sentiment.compute({"items": items}, None, None)["trend"], "a melhorar")
        self.assertEqual(sentiment.compute({"items": list(reversed([{**i, "tone": "negativo" if i["tone"] == "positivo"
                                                                     else "positivo"} for i in items]))}, None, None)["trend"],
                         "a piorar")
        self.assertEqual(sentiment.compute({"items": items[:2]}, None, None)["trend"], "estável")

    def test_nothing_available(self):
        out = sentiment.compute(None, None, None)
        self.assertEqual((out["overall_score"], out["label"], out["score"]), (0.0, "neutro", 0))
        self.assertIn("Sem dados de: notícias, analistas, insiders.", out["summary"])

    def test_labels(self):
        self.assertEqual([sentiment.label_of(x) for x in (-0.6, -0.2, 0.19, 0.2, 0.6)],
                         ["muito negativo", "negativo", "neutro", "positivo", "muito positivo"])


# ---------------------------------------------------------------------------------------------- dossier
class DossierTests(unittest.TestCase):
    INPUTS = {
        "profile": {"symbol": "X", "name": "X Corp", "price": 10.0, "quote_ts": "2026-11-15T12:00:00Z", "summary": "s" * 600,
                    "cross_listings": [{"symbol": "X.F"}], "sources": {"quote": "yfinance"}, "market_cap_usd": 1e9},
        "health": {"health_score": 83, "formulas": {"health": "…"}, "piotroski": {"points": 6, "available": 9,
                   "tests": {"roa_positivo": True, "sem_diluicao": False}}},
        "comps": {"target": {"symbol": "X", "name": "X Corp", "trailing_pe": 20.0}, "medians": {"trailing_pe": 25.0},
                  "peers": [{"symbol": "Y", "name": "Y Corp", "trailing_pe": 30.0, "market_cap": 5e9, "currency": "USD"}],
                  "target_minus_median": {"trailing_pe": -5}},
        "news": {"per_window": {"4h": 1, "24h": 0, "7d": 0, "30d": 1}, "items": [
            {"w": "4h", "title": "T1", "url": "https://a.com/1", "published_at": "2026-11-15T11:00:00Z", "relevance": 4,
             "tone": "negativo", "category": "legal", "summary": "Resumo 1", "triaged": True},
            {"w": "30d", "title": "T2", "url": "https://a.com/2", "published_at": "2026-10-20T09:00:00Z", "relevance": 2,
             "tone": "neutro", "category": "other", "summary": "Resumo 2", "triaged": True},
            {"w": "4h", "title": "T3", "url": "https://a.com/3", "published_at": "2026-11-15T11:50:00Z", "relevance": None,
             "tone": "neutro", "category": "other", "summary": None, "triaged": False}]},
        "forecast": {"summary": "base 153.040", "expected_12m": 215000},
        "technical": {"summary": "prosa", "signals": ["RSI14 de 42,03"]},
        "us_lead": {"applicable": False, "reason": "a ação pertence à sessão que lidera", "proxies": [{"symbol": "ES=F"}],
                    "market_state": {"open": False}},
    }

    def test_gaps_stay_as_null_and_are_listed(self):
        d = dossier.build(self.INPUTS)
        self.assertIsNone(d["sentiment"])
        self.assertIn("sentiment", d["gaps"])
        self.assertNotIn("profile", d["gaps"])
        self.assertEqual(list(d)[:2], ["profile", "indicators"])                # ordem estável (cache por conteúdo)

    def test_keeps_what_supports_a_reason_and_drops_metadata(self):
        d = dossier.build(self.INPUTS)
        self.assertEqual(d["profile"], {"symbol": "X", "name": "X Corp", "price": 10.0, "market_cap_usd": 1e9})
        self.assertEqual(d["health"]["piotroski"], {"points": 6, "available": 9, "failed": ["sem_diluicao"]})
        self.assertNotIn("formulas", d["health"])
        self.assertEqual(d["comps"]["peers"], [{"symbol": "Y", "trailing_pe": 30.0}])
        self.assertEqual(d["forecast"]["summary"], "base 153.040")              # números que só existem no resumo
        self.assertNotIn("summary", d["technical"])
        self.assertEqual(d["us_lead"], {"applicable": False, "reason": "a ação pertence à sessão que lidera"})

    def test_news_is_one_list_without_urls(self):
        n = dossier.build(self.INPUTS)["news"]
        self.assertEqual(n["items"][0], {"w": "4h", "title": "T1", "category": "legal", "relevance": 4,
                                         "tone": "negativo", "at": "2026-11-15T11:00", "summary": "Resumo 1"})
        self.assertNotIn("summary", n["items"][1])                              # relevância < 3: só o título
        self.assertTrue(n["items"][2]["por_triar"])

    def test_is_much_smaller_than_the_raw_inputs(self):
        raw = len(json.dumps(self.INPUTS, ensure_ascii=False))
        compact = len(json.dumps(dossier.build(self.INPUTS), ensure_ascii=False))
        self.assertLess(compact, raw * 0.75)


# ---------------------------------------------------------------------------------------------- segurança
class HookTests(unittest.TestCase):
    def test_fetch_guard(self):
        self.assertIsNone(hooks.fetch_problem("https://www.reuters.com/markets/samsung?page=2"))
        self.assertIn("http", hooks.fetch_problem("file:///c:/Users/x/.env"))
        self.assertIn("interno", hooks.fetch_problem("http://127.0.0.1:8080/x"))
        self.assertIn("interno", hooks.fetch_problem("http://192.168.1.10/admin"))
        self.assertIn("longos", hooks.fetch_problem("https://evil.example/?k=" + "A" * 400))   # exfiltração por URL

    def run_pre(self, built, tool, tool_input):
        import re
        outs = []
        for m in built["PreToolUse"]:
            if m.matcher is None or re.fullmatch(m.matcher, tool):
                for h in m.hooks:
                    outs.append(asyncio.run(h({"tool_name": tool, "tool_input": tool_input}, None, None)))
        return "deny" if any(o.get("hookSpecificOutput", {}).get("permissionDecision") == "deny" for o in outs) else "allow"

    def test_read_guard_only_allows_the_agent_folder(self):
        agent_dir = ROOT / "agents" / "pre_ipo_agent"
        built = hooks.build_hooks([], {"run_id": "teste-hooks", "agent": "t", "dirs": [str(agent_dir)]})
        self.assertEqual(self.run_pre(built, "Read", {"file_path": str(agent_dir / "scripts" / "deal_math.py")}), "allow")
        self.assertEqual(self.run_pre(built, "Read", {"file_path": str(ROOT / ".env")}), "deny")
        self.assertEqual(self.run_pre(built, "Read", {"file_path": str(agent_dir / ".." / ".." / ".env")}), "deny")
        self.assertEqual(self.run_pre(built, "Glob", {"pattern": "**/*.env", "path": str(Path.home())}), "deny")
        self.assertEqual(self.run_pre(built, "Glob", {"pattern": "../../*"}), "deny")
        no_dirs = hooks.build_hooks([], {"run_id": "teste-hooks", "agent": "t"})
        self.assertEqual(self.run_pre(no_dirs, "Read", {"file_path": str(agent_dir / "agent.yaml")}), "deny")

    def test_always_on_hooks_are_not_duplicated(self):
        built = hooks.build_hooks(["fetch_guard", "block_domains", "block_domains"], {"run_id": "teste-hooks", "agent": "t"})
        self.assertEqual(sum(m.matcher == "WebFetch" for m in built["PreToolUse"]), 2)   # fetch_guard + block_domains

    def test_web_agents_have_no_read_or_bash(self):
        """A4 — agentes que leem a web não podem ler ficheiros nem correr comandos."""
        for name in ("news_scan_agent", "relations_agent", "market_share_agent", "competitors_agent", "ipo_web_agent"):
            spec = load_agent(name)
            self.assertFalse({"Read", "Bash", "Write", "Edit", "Agent", "Glob", "Grep"} & set(spec.builtin_tools), name)


# ---------------------------------------------------------------------------------------------- cache e fluxo
class CacheKeyTests(unittest.TestCase):
    def test_content_key_ignores_volatile_fields(self):
        spec = load_agent("timing_agent")
        a = {"profile": {"symbol": "X", "price": 10.0, "quote_ts": "2026-11-15T12:00:00Z", "sources": {"q": "alpaca"}},
             "indicators": {"rsi14": 50, "provider": "yfinance"}}
        b = {"profile": {"symbol": "X", "price": 10.0, "quote_ts": "2026-11-15T12:05:00Z", "sources": {"q": "finnhub"}},
             "indicators": {"rsi14": 50, "provider": "tiingo"}}
        self.assertEqual(cache_key(spec, a), cache_key(spec, b))
        b["profile"]["price"] = 10.1                                            # o preço é conteúdo: muda a chave
        self.assertNotEqual(cache_key(spec, a), cache_key(spec, b))

    def test_llm_nodes_are_cached_by_content(self):
        for name in ("timing_agent", "forecast_agent", "debate_bull_agent", "debate_bear_agent", "rating_agent",
                     "rating_v1_agent"):
            spec = load_agent(name)
            self.assertTrue(spec.cache_ttl > 0 and spec.cache_key is None, name)
        self.assertNotEqual(cache_key(load_agent("debate_bull_agent"), {"ticker": "X", "dossier": {}, "role": "otimista"}),
                            cache_key(load_agent("debate_bear_agent"), {"ticker": "X", "dossier": {}, "role": "cético"}))


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.nodes = load_flow("ticker")

    def test_every_agent_of_the_flow_loads(self):
        for flow in ("ticker", "ipos", "ipo"):
            for node in load_flow(flow).values():
                names = ["rating_agent", "rating_v1_agent"] if node.agent.startswith("$") else [node.agent]
                for name in names:
                    spec = load_agent(name)
                    if spec.kind == "llm":
                        self.assertTrue(spec.system_prompt({}), name)
                        self.assertIsNotNone(spec.output_model, name)
                    else:
                        self.assertIsNotNone(spec.find("run.py"), name)

    def test_debate_runs_in_parallel_before_the_judge(self):
        self.assertEqual(deps(self.nodes["bull"], self.nodes), {"dossier", "profile"})
        self.assertEqual(deps(self.nodes["bear"], self.nodes), {"dossier", "profile"})
        self.assertTrue({"bull", "bear", "dossier"} <= deps(self.nodes["rating"], self.nodes))
        level = {n: i for i, layer in enumerate(layers(self.nodes)) for n in layer}
        self.assertEqual(level["bull"], level["bear"])
        self.assertLess(level["bear"], level["rating"])
        self.assertEqual(self.nodes["bull"].when, "$debate")

    def test_one_news_session_and_no_llm_sentiment(self):
        llm = sorted(n for n, node in self.nodes.items() if not node.agent.startswith("$")
                     and load_agent(node.agent).kind == "llm")
        self.assertEqual(llm, ["bear", "bull", "competitors", "forecast", "fundamental", "market_share", "news_scan",
                               "relations", "technical", "timing"])
        self.assertEqual(deps(self.nodes["sentiment"], self.nodes), {"profile", "news", "analysts", "insiders"})

    def test_judge_and_debaters_are_single_request_agents(self):
        for name in ("rating_agent", "rating_v1_agent", "debate_bull_agent", "debate_bear_agent", "timing_agent",
                     "forecast_agent", "fundamental_agent", "technical_agent"):
            self.assertTrue(load_agent(name).single_request, name)

    def test_timeouts_are_bounded(self):
        self.assertTrue(all(node.timeout <= 300 for node in self.nodes.values()))

    def test_judge_prompt_receives_both_cases(self):
        spec = load_agent("rating_agent")
        task = spec.task_tpl.safe_substitute({"ticker": "X", "now": "agora", "dossier": "{}", "bull": "CASO-BULL",
                                              "bear": "CASO-BEAR"})
        self.assertIn("CASO-BULL", task)
        self.assertIn("CASO-BEAR", task)
        self.assertNotIn("$", task)
        self.assertIn("evidence", spec.system_prompt({}))
        v1 = load_agent("rating_v1_agent").task_tpl.safe_substitute({"ticker": "X", "now": "agora", "dossier": "{}"})
        self.assertNotIn("$", v1)


if __name__ == "__main__":
    unittest.main()
