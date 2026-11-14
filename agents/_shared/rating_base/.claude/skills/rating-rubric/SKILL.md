---
name: rating-rubric
description: Rubrica de classificação de ações do Agentock (escala de 5 níveis, pesos por dimensão, calibração da confiança e regras obrigatórias). Usar sempre que for preciso decidir strong_sell / sell / hold / buy / strong_buy a partir do dossier.
---

# Rubrica de classificação

## Escala (horizonte por omissão: 3–12 meses)
- **strong_buy** — tese positiva forte em várias dimensões independentes, valorização com margem, sem risco binário próximo.
- **buy** — balanço claramente positivo, com riscos identificados.
- **hold** — sinais mistos, valorização justa, ou incerteza alta (ex.: resultados dentro de dias sem visibilidade).
- **sell** — balanço claramente negativo.
- **strong_sell** — deterioração em várias dimensões e/ou valorização muito esticada com catalisador negativo.

## Dimensões e peso indicativo
| Dimensão | Fonte no dossier | Peso |
|---|---|---|
| Fundamentais e valorização | fundamental, health, price_targets | 30% |
| Analistas e alvos | analysts, price_targets | 15% |
| Técnica e momentum | technical, indicators, health.momentum | 15% |
| Notícias e sentimento | news_*, sentiment | 15% |
| Posição competitiva | competitors, market_share, relations | 10% |
| Timing e eventos | timing, calendar, leads | 10% |
| Cenários | forecast | 5% |

Dimensões ausentes (`null`) não contam para o peso; mas cada uma ausente reduz a confiança.

## Calibração da confiança (0–1)
- Começa em 0,7. −0,05 por dimensão ausente. −0,1 se as dimensões se contradizem fortemente.
- −0,1 se há resultados ou evento binário nos próximos 7 dias (`calendar.days_to_earnings`).
- −0,1 se a ação é IPO recente (`profile.ipo_recente`) — pouco histórico.
- Nunca acima de 0,9. Abaixo de 0,4 → prefere **hold**.

## Versão curta (alertas no telemóvel) — obrigatória
- `headline`: 1 frase simples, até 110 caracteres, sem jargão. Ex.: "Empresa excelente, mas o preço já desconta o bom momento".
- `key_points`: 2–3 pontos de até 60 caracteres, no máximo um número por ponto, do dossier.
  Ex.: "Qualidade muito alta: Piotroski 9/9" · "Alvo médio 3,9% abaixo do preço" · "Resultados a 28 jan".
- Nada de "Falsificável", fórmulas, siglas sem explicação ou parênteses longos — isso fica nas razões.
- Formato português: "33 mil M USD", "3,9%", "28 de janeiro" — nunca "$33B"; sem siglas de período ("9M26", "T3").

## Regras obrigatórias
- 2 a 5 razões, cada uma ligada a uma dimensão e com o número do dossier que a suporta.
- 2 a 4 riscos concretos.
- Não inventes números. Percentagens e preços só se estiverem no dossier.
- `bull_case` / `bear_case`: uma frase cada.
