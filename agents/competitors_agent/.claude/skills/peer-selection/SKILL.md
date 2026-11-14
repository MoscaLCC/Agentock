---
name: peer-selection
description: Critérios para escolher concorrentes cotados comparáveis (mesmo negócio, dimensão, mercado), rejeitar fornecedores/clientes e validar símbolos.
---

# Seleção de peers

## Entra
- Concorre pelo mesmo cliente com produto substituto, em pelo menos um segmento relevante (> 20% da receita de um dos dois).
- Cotada e com símbolo que resolve em `mcp__market__profile`.
- Dimensão: idealmente entre 1/20 e 20× a market cap da empresa. Fora disso, só com `overlap` alta.
- Global: inclui concorrentes de outros mercados (ex.: Samsung ↔ SK Hynix, Micron, TSMC conforme o segmento).

## Não entra
- Fornecedores e clientes (ex.: montadoras de componentes para a Apple) — vão para `rejected_hints`.
- Conglomerados em que o segmento concorrente é < 10% da receita (overlap baixa; só se faltarem peers).
- Cotações secundárias da mesma empresa (ADR/GDR) — usa a principal.

## Overlap
- alta: mesmo produto principal; média: um segmento importante; baixa: sobreposição parcial.
