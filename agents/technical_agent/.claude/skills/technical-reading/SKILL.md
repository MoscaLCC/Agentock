---
name: technical-reading
description: Regras para ler indicadores técnicos já calculados (tendência, momentum, níveis, volume, volatilidade) e convertê-los num score de −2 a +2. Usar sempre que for preciso interpretar o JSON do technical_indicators_agent.
---

# Leitura técnica

## Tendência
- Preço acima da SMA50 e da SMA200, com SMA50 > SMA200 → alta. O contrário → baixa. Misto → lateral.
- `cross_last_20d`: "golden" (SMA50 cruzou acima da SMA200) reforça alta; "death" reforça baixa.
- Sem SMA200 (menos de 200 sessões): a tendência longa é **indefinida** — diz isso.

## Momentum
- RSI14 > 70 sobrecomprado (risco de correção, não sinal de venda por si só); < 30 sobrevendido.
- MACD: `hist` > 0 e a subir → momentum positivo; < 0 → negativo.
- Retornos 1m/3m vs 6m/1a: aceleração ou abrandamento.

## Níveis
- Suportes/resistências: usa só os de `levels`. Distância ao máximo de 52 semanas < 5% → perto de máximos.
- Bollinger `pct_b` > 1 → acima da banda superior (esticado); < 0 → abaixo da inferior.
- `atr_zones`: referência de stop/alvo a 2 ATR.

## Volume e volatilidade
- `volume.rel` > 1.5 confirma o movimento do dia; < 0.7 é movimento pouco participado.
- `atr_pct` > 4% ou `volatility_ann_pct` > 50% → ação muito volátil (aumenta o risco).

## Mercados com limite diário (China, Coreia)
- `price_limit.near_limit` = true → a ação está perto do limite diário; o preço pode não refletir a procura/oferta real. Menciona em `caveats`.

## Score
- +2: alta clara + momentum positivo + volume a confirmar.
- +1: alta ou momentum positivo, sem confirmação total.
- 0: lateral ou sinais contraditórios.
- −1 / −2: espelho do positivo.
- Sobrecompra/sobrevenda extrema puxa o score 1 nível na direção contrária.
