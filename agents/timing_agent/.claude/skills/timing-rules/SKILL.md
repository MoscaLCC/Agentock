---
name: timing-rules
description: Regras para avaliar o momento de entrada numa ação — níveis, extensão, eventos binários próximos, sinais das sessões que lideram, limites diários e lock-ups.
---

# Regras de timing

## Esperar (entry_quality = "esperar")
- Resultados ou evento binário nos próximos 5 dias (`calendar.days_to_earnings` ≤ 5).
- Fim de lock-up nos próximos 10 dias (`ipo_lifecycle.lockup.days_until`), sobretudo se `days_to_trade_locked` > 10.
- Preço colado ao limite diário (`indicators.price_limit.near_limit`).

## Má
- Preço muito esticado: RSI14 > 75, ou `bollinger.pct_b` > 1, ou > 15% acima da SMA50.
- Rompeu um suporte com volume (`volume.rel` > 1,5) em tendência de baixa.

## Boa
- Tendência de alta com recuo para perto de um suporte (≤ 3% acima) ou da SMA50, RSI entre 40 e 60.
- Sinais das sessões que lideram (`*_lead.bias`) a favor, com confiança ≥ 0,6.

## Zonas
- Zona de compra: entre o suporte mais próximo e o preço atual (ou SMA50), só com níveis dos dados.
- Stop de referência: o suporte seguinte ou `atr_zones.stop_2atr`.

## Sessões que lideram
- Se uma sessão aplicável tiver `|signal_pct|` > 1% com confiança ≥ 0,6, a abertura deverá refletir isso: diz-o em `next_session_bias` e evita comprar contra um gap provável.

## Score
- boa +1/+2, neutra 0, má −1/−2, esperar 0 ou −1.
