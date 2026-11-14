"""Servidor MCP in-process `market`: expõe o router de dados aos agentes LLM.

No agent.yaml:  market_tools: [quote, news, eod]   ->  tools mcp__market__quote, ...
"""
import asyncio
import json

from claude_agent_sdk import create_sdk_mcp_server, tool

from .data import DataUnavailable, get_router

SYM = {"type": "string", "description": "Símbolo no formato yfinance (ex.: AAPL, 0700.HK, 600519.SS, 005930.KS)"}

SPECS = {
    "quote": ("Cotação atual (preço, fecho anterior, variação %).", {"symbol": SYM}),
    "eod": ("Preços diários OHLCV dos últimos N dias.",
            {"symbol": SYM, "days": {"type": "integer", "default": 60}}),
    "intraday": ("Candles intraday (5m por omissão) dos últimos dias.",
                 {"symbol": SYM, "interval": {"type": "string", "default": "5m"}, "days": {"type": "integer", "default": 2}}),
    "profile": ("Perfil: nome, bolsa, moeda, setor, indústria, país, market cap.", {"symbol": SYM}),
    "news": ("Notícias recentes da ação, de várias fontes, deduplicadas, mais recentes primeiro.",
             {"symbol": SYM, "limit": {"type": "integer", "default": 30}}),
    "analyst_recs": ("Contagem de recomendações dos analistas (strong buy … strong sell).", {"symbol": SYM}),
    "price_targets": ("Preços-alvo dos analistas: atual, mínimo, máximo, média, mediana.", {"symbol": SYM}),
    "upgrades": ("Últimas alterações de rating por casa de análise (EUA), com preço-alvo.", {"symbol": SYM}),
    "peers": ("Lista de concorrentes (EUA; pode ter ruído — validar).", {"symbol": SYM}),
    "calendar": ("Próximos resultados, ex-dividendo e estimativas.", {"symbol": SYM}),
    "search": ("Procura cotações por nome (deteta ADR, A/H, GDR).", {"query": {"type": "string"}}),
    "fx": ("Taxa de câmbio, ex.: USD/KRW.", {"pair": {"type": "string"}}),
    "ipo_calendar": ("IPOs previstos nos próximos N dias.", {"days": {"type": "integer", "default": 30}}),
}


def _schema(props: dict) -> dict:
    required = [k for k, v in props.items() if "default" not in v]
    return {"type": "object", "properties": props, "required": required}


def _make(cap: str):
    desc, props = SPECS[cap]

    @tool(cap, desc, _schema(props))
    async def handler(args):
        args = dict(args)
        symbol = args.pop("symbol", None) or args.pop("query", None) or args.pop("pair", None)
        limit = args.pop("limit", None)  # cortamos aqui, para a cache não depender do limite
        try:
            res = await asyncio.to_thread(get_router().get, cap, symbol, **args)
        except DataUnavailable as e:
            return {"content": [{"type": "text", "text": f"Indisponível: {e}"}], "is_error": True}
        data = res.data[:limit] if limit and isinstance(res.data, list) else res.data
        payload = {"provider": res.provider, "cached": res.cached, "data": data}
        return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, default=str)}]}

    return handler


def build_market_server(caps: list[str]):
    unknown = set(caps) - set(SPECS)
    if unknown:
        raise ValueError(f"market_tools desconhecidas: {sorted(unknown)}")
    return create_sdk_mcp_server(name="market", tools=[_make(c) for c in caps])
