---
name: relations-sources
description: Onde encontrar relações empresariais oficiais por mercado (SEC Exhibit 21/8, DART, CNINFO, HKEXnews, relatórios anuais) e como priorizar o que é relevante.
---

# Fontes de relações empresariais

| Mercado | Subsidiárias / participações | Clientes e fornecedores |
|---|---|---|
| EUA e ADRs | Exhibit 21 (10-K) / Exhibit 8 (20-F) → `mcp__market__subsidiaries` | 10-K "Risk Factors" e "Customers" (concentração > 10%) |
| Coreia | DART: relatório anual (사업보고서), "계열회사 현황" → `mcp__market__filings` dá as ligações | relatório anual, imprensa |
| China A | CNINFO: relatório anual (年度报告), secção de partes relacionadas (关联方) | idem |
| Hong Kong | HKEXnews: relatório anual, "Principal subsidiaries" | idem |
| Japão / Europa | relatório anual / Universal Registration Document | idem |

## Prioridade
1. Empresa-mãe e acionista de controlo (com %).
2. Participadas cotadas (o preço delas mexe com o valor da empresa).
3. Clientes ou fornecedores com > 10% da receita/custos, ou fornecedor único.
4. Joint ventures estratégicas.
A lista completa do Exhibit 21 não interessa: escolhe as subsidiárias que operam os negócios principais.
