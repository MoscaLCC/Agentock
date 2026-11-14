"""Orquestrador. Trigger manual.

  python flow.py AAPL            # uma ação
  python flow.py --universe      # as ~500 maiores (sequencial, caro)
  python flow.py --universe --top 20
"""
import argparse
import asyncio
import sys

import core.env  # noqa: F401  (carrega o .env)
from core.runner import run_agent
from core.schemas import Synthesis


async def finalize(synthesis: Synthesis) -> dict:
    """Camada final: grava no histórico e verifica alteração de estado (notifica se houver)."""
    await run_agent("memory_agent", synthesis=synthesis)
    return await run_agent("change_alert_agent", synthesis=synthesis)


async def analyze(ticker: str, hours: int):
    news = await run_agent("news_4_hours_agent", ticker=ticker, hours=hours)
    print(news.model_dump_json(indent=2))
    # TODO camadas 1-3: dados, análises e síntese -> Synthesis -> await finalize(synthesis)
    return news


async def main(args) -> None:
    if args.universe:
        tickers = [u["symbol"] for u in await run_agent("universe_agent", top_n=args.top, refresh=args.refresh)]
    elif args.ticker:
        tickers = [args.ticker.upper()]
    else:
        sys.exit("Indica um ticker ou --universe")

    for t in tickers:
        try:
            await analyze(t, args.hours)
        except Exception as e:  # uma ação falhada não pára as restantes
            print(f"[{t}] ERRO: {e}", file=sys.stderr)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("ticker", nargs="?")
    p.add_argument("--universe", action="store_true")
    p.add_argument("--top", type=int, default=500)
    p.add_argument("--refresh", action="store_true", help="ignorar cache do universo")
    p.add_argument("--hours", type=int, default=4)
    asyncio.run(main(p.parse_args()))
