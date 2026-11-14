---
name: news-triage
description: Triagem de notícias financeiras sobre uma ação — como pesquisar (APIs + web, multilíngue), confirmar datas, deduplicar e pontuar relevância e tom. Usar sempre que for preciso recolher notícias de um ticker numa janela de tempo.
---

# News triage

## 1. Pesquisa
- Primeiro `mcp__market__news` (Finnhub, Alpaca, yfinance, EODHD, akshare — já deduplicadas por URL, com hora exata).
- Depois web: `<TICKER> stock news`, `<Empresa> news`, `<Empresa> earnings`, `<Empresa> analyst`, e na língua local
  (ver `references/sources_by_market.md`). Janelas longas (7–30 dias) dependem mais da web: as APIs cobrem ~7 dias.
- Preferir fontes primárias (comunicados, reguladores, agências) a agregadores.

## 2. Confirmar data
- Itens das APIs já trazem `published_at`. Itens só da web: abre com WebFetch e lê a hora de publicação.
- Passa todos os timestamps a `python scripts/check_window.py --hours <N> <ts...>`; descarta `inside != true`.

## 3. Deduplicar
- Mesma história em várias fontes → 1 item (a fonte mais primária). Para listas grandes:
  `python scripts/dedupe.py --json '[{"title":…,"url":…}, …]'` devolve os grupos.

## 4. Relevância (1-5)
- 5: resultados, guidance, M&A, ação regulatória, suspensão — move o preço
- 4: upgrade/downgrade relevante, contrato grande, insider trade grande, mudança de CEO
- 3: produto/parceria, comentário de executivo
- 2: opinião/análise sem informação nova
- 1: marginal

## 5. Tom (para a ação)
- `positivo` / `negativo` / `neutro` — o efeito provável no preço, não o tom do texto.

## Output
Segue `templates/output_example.json`. Ordena por relevância descendente.
