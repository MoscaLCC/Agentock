"""Trigger manual do Agentock.

  python flow.py AAPL                     # fluxo 'ticker' para uma ação (aceita nome: "Samsung", ou código: 005930)
  python flow.py AAPL --rating v2         # classificação com debate bull/bear (v1 = um só LLM)
  python flow.py AAPL --hours 48          # parâmetros do trigger (atalho de --set hours=48)
  python flow.py AAPL --set k=v           # qualquer parâmetro do fluxo
  python flow.py AAPL --only indicators   # só um nó
  python flow.py AAPL --dry-run           # mostra o DAG sem correr
  python flow.py AAPL --no-cache          # ignora a cache de outputs
  python flow.py AAPL --verbose           # mostra o output de todos os nós
  python flow.py --universe --top 20      # as N maiores (ver também --parallel, --resume, --yes)
  python flow.py --ipos [--days 30]       # calendário de IPOs + análise de cada IPO acima do limiar
  python flow.py --ipo "Nome"             # análise de um IPO
  python flow.py --backfill               # preenche retornos das classificações passadas
  python flow.py --eval                   # relatório de acerto (Fase 7)
  python flow.py --report AAPL            # página HTML com o histórico da ação
"""
import argparse
import asyncio
import json
import sys

import core.env  # noqa: F401  (carrega o .env)
from core.orchestrator import flow_defaults, layers, load_flow, run_flow
from core.runner import to_jsonable

RATING = {"v1": "rating_v1_agent", "v2": "rating_agent"}


def print_report(label: str, report, verbose: bool = False, final: str = "guard") -> None:
    print(f"\n=== {label}  run {report.run_id}")
    for name, r in report.results.items():
        cost = f"${r.cost_usd:.4f}" if r.cost_usd else "-"
        dur = f"{(r.duration_ms or 0) / 1000:.1f}s"
        flag = "cache" if r.cached else r.status
        print(f"  {name:16} {flag:8} {cost:>9} {dur:>8}  {(r.error or '')[:110]}")
    print(f"  {'total':16} {'':8} ${report.cost_usd:.4f}")
    shown = report.results.items() if verbose else [(final, report.results.get(final))]
    for name, r in shown:
        if r is not None and r.status == "ok":
            print(f"\n--- {name}\n{json.dumps(to_jsonable(r.output), ensure_ascii=False, indent=2, default=str)}")


def parse_sets(items: list[str]) -> dict:
    out = {}
    for it in items or []:
        k, _, v = it.partition("=")
        try:
            out[k] = json.loads(v)
        except json.JSONDecodeError:
            out[k] = v
    return out


async def run_ticker(ticker: str, a, params: dict):
    report = await run_flow(a.flow, {"ticker": ticker, **params}, only=a.only, use_cache=not a.no_cache)
    print_report(ticker, report, a.verbose)
    return report


def build_params(a) -> dict:
    params = parse_sets(a.set)
    if a.hours is not None:
        params["hours"] = a.hours
    if a.rating:
        params.update(rating_agent=RATING[a.rating], rating_version=a.rating)
    return params


async def main(a) -> None:
    params = build_params(a)
    if a.dry_run:
        print("defaults:", flow_defaults(a.flow))
        for i, layer in enumerate(layers(load_flow(a.flow)), 1):
            print(f"camada {i}: {', '.join(layer)}")
        return
    if a.backfill or a.eval:
        from tools import evaluation
        if a.backfill:
            print(json.dumps(evaluation.backfill(), ensure_ascii=False, indent=2))
        if a.eval:
            print(evaluation.report_text(evaluation.build_report()))
        return
    if a.report:
        from tools import history_page
        print(history_page.build(a.report))
        return
    if a.ipos or a.ipo:
        from tools import ipo_flow
        await ipo_flow.main(a, params)
        return
    if a.universe:
        from tools import universe_run
        await universe_run.main(a, params, run_ticker)
        return
    if not a.ticker:
        sys.exit("Indica um ticker (ou --universe, --ipos, --backfill, --eval, --report)")
    await run_ticker(a.ticker, a, params)


def cli(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("ticker", nargs="?")
    p.add_argument("--flow", default="ticker")
    p.add_argument("--rating", choices=["v1", "v2"])
    p.add_argument("--hours", type=int)
    p.add_argument("--set", action="append", metavar="K=V")
    p.add_argument("--only")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--universe", action="store_true")
    p.add_argument("--top", type=int, default=500)
    p.add_argument("--parallel", type=int, default=1)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--yes", action="store_true", help="confirma a execução do universo depois da estimativa de custo")
    p.add_argument("--refresh", action="store_true", help="ignorar cache do universo")
    p.add_argument("--ipos", action="store_true")
    p.add_argument("--ipo")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--backfill", action="store_true")
    p.add_argument("--eval", action="store_true")
    p.add_argument("--report")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main(cli()))
