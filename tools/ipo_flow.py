"""Fluxos de IPOs (chamado pelo flow.py).

  python flow.py --ipos [--days 30]              # calendário + análise de cada IPO acima do limiar (máx. max_ipos)
  python flow.py --ipos --set analyze=false      # só o calendário
  python flow.py --ipo "Nome da empresa"         # análise de um IPO
"""
import json

from core.orchestrator import run_flow
from core.runner import to_jsonable


def _table(ipos: list[dict]) -> str:
    lines = [f"{'data':10}  {'símbolo':8}  {'bolsa':22}  {'preço':12}  {'dimensão (USD)':>14}  nome"]
    for i in ipos:
        v = f"{i['value_usd'] / 1e9:.2f} mil M" if i.get("value_usd") else "por divulgar"
        lines.append(f"{i.get('date') or '':10}  {i.get('symbol') or '—':8}  {(i.get('exchange') or '—')[:22]:22}  "
                     f"{str(i.get('price_range') or '—'):12}  {v:>14}  {i.get('name')}")
    return "\n".join(lines)


async def main(a, params: dict) -> None:
    from flow import print_report
    analyze = str(params.pop("analyze", "true")).lower() != "false"
    max_ipos = int(params.pop("max_ipos", 5))
    if a.ipo:
        items = [{"name": a.ipo}]
    else:
        rep = await run_flow("ipos", {"days": a.days, **params}, use_cache=not a.no_cache)
        res = rep.results["calendar"]
        if res.status != "ok":
            print(f"calendário falhou: {res.error}")
            return
        out = res.output
        print(f"\nIPOs nos próximos {out['days']} dias (≥ {out['min_value_usd'] / 1e6:.0f} M USD, sem SPACs) — "
              f"excluídos: {out['excluded']} — novos: {len(out['new'])}\n")
        print(_table(out["ipos"]))
        items = out["ipos"][:max_ipos]
    if not analyze:
        return
    for it in items:
        rep = await run_flow("ipo", {"ipo": it, "ticker": it.get("symbol") or it.get("name"), **params},
                             use_cache=not a.no_cache)
        print_report(f"IPO {it.get('name')}", rep, a.verbose, final="ipo_memory")
        r = rep.results.get("pre_ipo")
        if r and r.status == "ok":
            print(json.dumps(to_jsonable(r.output), ensure_ascii=False, indent=2))
