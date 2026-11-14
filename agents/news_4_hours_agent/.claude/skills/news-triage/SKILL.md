---
name: news-triage
description: Triagem de notícias financeiras sobre uma ação — como pesquisar, confirmar datas, deduplicar e pontuar relevância. Usar sempre que for preciso recolher notícias recentes de um ticker.
---

# News triage

## Pesquisa
- Queries mínimas: `<TICKER> stock news`, `<Empresa> news today`, `<Empresa> earnings`, `<Empresa> SEC filing`, `<Empresa> analyst upgrade downgrade`.
- Preferir fontes primárias (comunicados da empresa, SEC, Reuters, Bloomberg, WSJ) a agregadores.

## Confirmar data
- Abre a página com WebFetch e procura a hora de publicação (meta tags, byline).
- Passa todos os timestamps a `python scripts/check_window.py --hours <N> <ts...>`; descarta `inside != true`.

## Deduplicar
- Mesma história em várias fontes => 1 item, a fonte mais primária.

## Relevância (1-5)
- 5: resultados, guidance, M&A, ação regulatória, halt — move o preço
- 4: upgrade/downgrade relevante, contrato grande, insider trade grande
- 3: notícia de produto/parceria, comentário de executivo
- 2: opinião/análise sem informação nova
- 1: marginal

## Output
Segue `templates/output_example.json` (na raiz do agente).
