"""Trigger manual do Agentock.

  python flow.py AAPL                     # fluxo 'ticker' para uma ação
  python flow.py AAPL --hours 48          # parâmetros do trigger
  python flow.py AAPL --only news_4h      # só um nó
  python flow.py AAPL --dry-run           # mostra o DAG sem correr
  python flow.py AAPL --no-cache          # ignora a cache de outputs
  python flow.py --universe --top 20      # as N maiores (sequencial)
"""
import argparse
import asyncio
import json
import sys

import core.env  # noqa: F401  (carrega o .env)
from core.orchestrator import layers, load_flow, run_flow
from core.runner import run_agent, to_jsonable


def print_report(ticker: str, report) -> None:
    print(f"\n=== {ticker}  run {report.run_id}")
    for name, r in report.results.items():
        cost = f"${r.cost_usd:.4f}" if r.cost_usd is not None else "-"
        dur = f"{(r.duration_ms or 0) / 1000:.1f}s"
        flag = "cache" if r.cached else r.status
        print(f"  {name:22} {flag:7} {cost:>9} {dur:>8}  {r.error or ''}")
    print(f"  {'total':22} {'':7} ${report.cost_usd:.4f}")
    for name, r in report.results.items():
        if r.status == "ok":
            print(f"\n--- {name}\n{json.dumps(to_jsonable(r.output), ensure_ascii=False, indent=2, default=str)}")


async def main(a) -> None:
    if a.dry_run:
        for i, layer in enumerate(layers(load_flow(a.flow)), 1):
            print(f"camada {i}: {', '.join(layer)}")
        return
    if a.universe:
        res = await run_agent("universe_agent", top_n=a.top, refresh=a.refresh)
        if res.status != "ok":
            sys.exit(f"universe_agent falhou: {res.error}")
        tickers = [u["symbol"] for u in res.output]
    elif a.ticker:
        tickers = [a.ticker.upper()]
    else:
        sys.exit("Indica um ticker ou --universe")

    for t in tickers:
        report = await run_flow(a.flow, {"ticker": t, "hours": a.hours}, only=a.only, use_cache=not a.no_cache)
        print_report(t, report)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("ticker", nargs="?")
    p.add_argument("--flow", default="ticker")
    p.add_argument("--hours", type=int, default=4)
    p.add_argument("--only")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--universe", action="store_true")
    p.add_argument("--top", type=int, default=500)
    p.add_argument("--refresh", action="store_true", help="ignorar cache do universo")
    asyncio.run(main(p.parse_args()))
