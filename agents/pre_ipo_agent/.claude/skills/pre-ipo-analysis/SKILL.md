---
name: pre-ipo-analysis
description: Metodologia de análise pré-IPO do Agentock (adaptada das skills bigdata-pre-ipo-analysis): estrutura da oferta do prospeto, financeiras, peers cotados, janela de IPOs, sentimento, debate e classificação Subscrever/Neutro/Evitar.
---

# Análise pré-IPO

## Âmbito
- Só IPOs ainda não cotados. Se já negoceia, diz isso e analisa como ação normal noutro fluxo.
- "Não divulgado" sempre que o prospeto não traz o número — **nunca** estimativas apresentadas como factos.

## Pesquisa (por esta ordem; regista fonte e data de cada facto)
a. **Prospeto** (S-1/F-1/424B4 nos EUA; HKEXnews; DART; CNINFO; JPX): intervalo de preço, ações oferecidas (primárias vs secundárias), greenshoe, ações pós-oferta, subscritores (bookrunners), data e bolsa, uso dos fundos, **lock-up** (prazos e quem), classes de ações e direitos de voto, investidores-âncora.
b. **Financeiras**: 2 últimos exercícios + período intercalar — receita, margem bruta, resultado operacional, resultado líquido, cash flow operacional, FCF, caixa e dívida.
c. **Negócio**: modelo, segmentos, clientes, gestão, rondas de financiamento e última avaliação privada.
d. **Peers cotados** (3–6) com múltiplos atuais (EV/Sales, EV/EBITDA, P/E) via `mcp__market__financials`.
e. **Janela de IPOs**: estreias recentes do setor e desempenho desde então (`mcp__market__eod`).
f. **Sentimento**: notícias dos últimos 90 dias.

## Matemática
- `python scripts/deal_math.py` para valorização implícita (preço × ações pós-oferta), free float e múltiplos implícitos. Confere que bate com o que o prospeto diz.

## Classificação
- **subscrever**: valorização com desconto (ou prémio justificado por crescimento superior) face aos peers, financeiras sólidas, procura forte, janela favorável, governação aceitável.
- **evitar**: valorização exigente sem suporte, perdas sem caminho claro, vendedores maioritariamente secundários, governação fraca (classes com supervoto + lock-up curto), janela fraca.
- **neutro**: sinais mistos ou informação insuficiente (muitos campos não divulgados).
- Confiança ≤ 0,6 se faltarem financeiras auditadas ou o intervalo de preço.

## Qualidade
- Cada número com fonte; bull e bear específicos e falsificáveis; `watch_points` com datas (fixação do preço, estreia, fim do lock-up).
