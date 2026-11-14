---
name: sentiment-rubric
description: Rubrica para medir o sentimento de uma ação a partir de notícias (tom × relevância), consenso de analistas e insiders (MSPR), com tendência entre janelas.
---

# Rubrica de sentimento

## Notícias
- Por item: tom (+1 / 0 / −1) × peso da relevância (5→3, 4→2, 3→1, 2→0,5, 1→0,25).
- Score de notícias = soma ponderada / soma dos pesos (fica entre −1 e +1).
- Notícias repetidas entre janelas contam uma vez.

## Analistas
- `consensus_score` (−2…+2) ÷ 2 → −1…+1. Ajusta ±0,1 pela `trend` e pelo saldo de `changes_90d`.

## Insiders (EUA)
- MSPR (−100…+100) ÷ 100. Compras de insiders são sinal mais forte do que vendas (vendas são muitas vezes planeadas).

## Agregado
- 50% notícias, 35% analistas, 15% insiders (redistribui os pesos se faltar alguma fonte).
- Rótulos: ≤ −0,6 muito negativo; ≤ −0,2 negativo; < 0,2 neutro; < 0,6 positivo; resto muito positivo.
- Escala −2…+2: arredonda overall × 2,5 ao inteiro (limitado a ±2).

## Tendência
- Score das janelas 4h+24h vs 7d+30d: diferença > +0,2 a melhorar; < −0,2 a piorar; senão estável.
