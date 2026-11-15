# Baseline — Agentock antes da Fase 10

> Medido em 2026-11-15, antes de qualquer alteração de código. Nenhuma análise foi corrida para isto: tudo vem de
> dados já gravados, mais uma experiência de 0,01 USD com o Haiku (secção 4).
> Reproduzir: `python tools/measure.py` (resumo), `--run RUN_ID` (uma execução), `--json` (para comparar depois).

## 1. De onde vêm os números

| Fonte | O que dá |
|---|---|
| `data/agentock.db`, tabela `agent_outputs` (260 linhas, 25 execuções) | custo, duração, turnos, estado e cache por nó |
| Transcrições das sessões dos agentes em `~/.claude/projects/*Agentock-agents-*` (93 sessões) | tokens por modelo, pedidos à API, o que vai no 1.º pedido |
| `data/logs/<run_id>.jsonl` | cada tool call e o tamanho da resposta |
| `data/runs/<run_id>/rating_agent/dossier.json` | o dossier que a classificação recebeu |

O `agent_outputs` não guardava tokens. Cada nó LLM foi ligado à sua sessão pelo custo (igual até ao 6.º decimal) e pela
hora de fim; assim há tokens para todos os nós LLM das 6 execuções completas.

## 2. Por análise (fluxo `ticker`, 29 nós)

| Execução | Nós ok | Falhas / skips | Nós em cache | Custo USD | Turnos | Tempo real | Mínimo possível (DAG) | Input novo | Cache write | Cache read | Output |
|---|---|---|---|---|---|---|---|---|---|---|---|
| AAPL 12:58 (v2, sem créditos na classificação) | 25/29 | 1 / 3 | 4 | 1,36 | 90 | 197 s | 144 s | 159,0k | 310,7k | 763,9k | 34,8k |
| AAPL 13:51 (v2, quase tudo em cache) | 29/29 | 0 / 0 | 15 | 1,72 | 33 | 130 s | 105 s | 46,1k | 298,8k | 418,5k | 14,7k |
| SSU 16:25 (v2) | 26/29 | 2 / 1 | 0 | 2,57 | 97 | 185 s | 138 s | 207,4k | 482,3k | 996,5k | 37,2k |
| 005930.KS 17:06 (v2) | 27/29 | 2 / 0 | 3 | 2,10 | 99 | 178 s | 117 s | 209,3k | 343,6k | 1 141,2k | 43,5k |
| NVDA 17:12 (v2) | 29/29 | 0 / 0 | 0 | 2,43 | 104 | 188 s | 134 s | 231,4k | 394,9k | 1 308,9k | 50,9k |
| CPNG 22:51 (v2) | 29/29 | 0 / 0 | 1 | 2,92 | 97 | 292 s | 203 s | 296,3k | 626,5k | 1 231,1k | 69,1k |

**Análise fria (média de SSU, 005930.KS, NVDA, CPNG): 2,50 USD · 1,92 M tokens · 211 s · 99 turnos.**
Dos 1,92 M tokens, 1,17 M são leituras de cache, 0,46 M escritas de cache, 0,24 M input novo e 0,05 M output.

Classificações de referência gravadas: AAPL hold 0,60 (v2, guard: 35 números, 0 por verificar); 005930.KS compra 0,55
(v2); 9988.HK hold 0,40 (v1, fluxo ainda com 18 nós — não há execução completa de 9988.HK).

## 3. Por nó (média das execuções reais, sem cache)

| Nó | Modelo | n | Custo | Duração média (máx.) | Turnos | Pedidos API | Input novo | Cache write | Cache read | Output |
|---|---|---|---|---|---|---|---|---|---|---|
| rating (v2) | opus + 2× sonnet | 5 | 0,604 | 43,6 s (47) | 6,0 | 4,0 | 20,8k | 103,0k | 162,4k | 4,8k |
| forecast | opus | 6 | 0,242 | 21,7 s (29) | 4,0 | 2,0 | 5,3k | 26,2k | 29,2k | 2,0k |
| timing | opus | 6 | 0,232 | 15,6 s (19) | 4,0 | 2,0 | 5,1k | 26,2k | 28,9k | 1,6k |
| news_30d | sonnet | 5 | 0,214 | 33,5 s (47) | 11,0 | 5,0 | 41,5k | 37,6k | 141,5k | 5,9k |
| market_share | sonnet | 3 | 0,190 | 38,8 s (55) | 7,7 | 4,0 | 45,0k | 38,2k | 97,9k | 6,2k |
| relations | sonnet | 5 | 0,185 | 53,2 s (154) | 12,0 | 4,0 | 53,3k | 54,3k | 139,4k | 10,7k |
| news_4h | sonnet | 6 | 0,167 | 18,9 s (28) | 9,7 | 4,7 | 13,4k | 34,7k | 121,9k | 2,6k |
| news_24h | sonnet | 5 | 0,166 | 23,4 s (30) | 9,6 | 4,4 | 16,1k | 32,9k | 111,4k | 3,4k |
| news_7d | sonnet | 5 | 0,154 | 25,2 s (37) | 9,6 | 4,6 | 21,4k | 26,4k | 130,6k | 4,2k |
| competitors | sonnet | 5 | 0,152 | 26,0 s (38) | 16,0 | 4,0 | 7,4k | 29,9k | 92,2k | 3,3k |
| sentiment | sonnet | 6 | 0,145 | 15,8 s (23) | 5,7 | 2,8 | 7,6k | 31,2k | 60,6k | 2,4k |
| fundamental | sonnet | 4 | 0,102 | 10,7 s (14) | 4,0 | 2,0 | 3,0k | 23,7k | 25,6k | 1,3k |
| technical | haiku | 5 | 0,006 | 14,0 s (20) | 4,0 | 2,0 | 2,3k | 23,4k | 26,7k | 2,6k |
| comps (script) | — | 5 | 0 | 7,5 s (9) | — | — | — | — | — | — |
| restantes scripts | — | — | 0 | 1,4–3,6 s | — | — | — | — | — | — |

Onde vai o dinheiro: classificação 24%, as 4 notícias 28%, timing + forecast 19%, concorrentes + relações + quotas 21%.

## 4. O achado principal: ~45 mil tokens de contexto alheio por sessão LLM

O 1.º pedido de cada agente já leva **20–24 mil tokens**, mesmo quando a tarefa tem 150 caracteres; ao 2.º pedido
entram mais **7–8 mil**. Quase nada disto é do Agentock:

| O que vai no contexto | Tamanho | De onde vem |
|---|---|---|
| Definições das 16 tools internas do Claude Code (Bash, PowerShell, Edit, Agent, ScheduleWakeup…) | ~40 000 caracteres | `allowed_tools` só dá permissão; não tira as tools do contexto |
| Lista de skills (inclui skills globais que o agente nunca usa) | ~7 500 | `setting_sources=["project"]` |
| Lista de tipos de subagente | ~3 400 | tool `Agent` disponível em todos os agentes |
| Instruções dos conectores MCP da conta + lista de tools diferidas (Gmail, Drive, Bilance, FMP…) | 13 000–34 000 | sem `strict_mcp_config`, cada agente herda os conectores do claude.ai |
| Memória do Claude Code do projeto (`MEMORY.md`) e email do utilizador | ~900 | sessão normal do Claude Code |
| **Prompt do agente (system + skill)** | **1 500–4 500** | Agentock |

Além disso, cada agente gasta **um pedido inteiro só para carregar a sua skill** (1–3 mil caracteres).

Experiência (technical_agent, Haiku, mesmos inputs gravados da CPNG):

| Variante | Pedidos | Tokens de input processados | Custo | Tempo | Leitura |
|---|---|---|---|---|---|
| Atual | 2 (4 turnos) | 51 466 | 0,00734 USD | 14,4 s | lateral / neutro |
| Isolada (`tools=[]`, `skills=[]`, `strict_mcp_config`, skill no system prompt) | 1 (2 turnos) | 6 298 | 0,00213 USD | 11,6 s | lateral / neutro |

**−88% de tokens e −71% de custo, com a mesma leitura.** Extrapolando para as 13 sessões + 2 subagentes de uma
análise, cerca de 1,2 M dos 1,92 M tokens (≈ 63%) são este overhead. Nos agentes Opus (timing, forecast) ele é ~85%
do custo.

Isto é também um problema de **segurança**: os agentes que leem a web (notícias, relações, quotas, IPOs) correm com os
conectores pessoais da conta visíveis no contexto (Gmail, Google Drive, finanças). As tools não estão em
`allowed_tools`, por isso uma chamada seria recusada, mas não deviam sequer estar lá.

## 5. Dossier e notícias

- **Dossier** (23 inputs): 40–55 mil caracteres no prompt do juiz (≈ 20 mil tokens) e 44–60 mil no ficheiro que cada
  subagente lê (gravado com `indent=1`, +10%). É lido 3 vezes (juiz, bull, bear). Maiores fatias: notícias 4h+24h+7d+30d
  13,2k, quotas de mercado 4,1k, comps 3,9k, relações 3,7k, forecast 3,0k, técnica 2,5k.
- **Notícias**: 4 agentes, 4 chamadas iguais a `mcp__market__news` (14–24 mil caracteres cada), ~10 turnos cada.
  Itens repetidos entre janelas: AAPL 28 → 15 únicos, 005930.KS 13 → 6, NVDA 45 → 21, CPNG 15 → 13 (**45% de
  duplicados**). Custam 0,70 USD e ~1,05 M tokens por análise e ocupam os 4 lugares do semáforo LLM logo no arranque.

## 6. Tempo e caminho crítico

- O orquestrador corre **por camadas**: uma camada só arranca quando o nó mais lento da anterior termina. Tempo real
  médio 211 s; se cada nó arrancasse quando as suas dependências acabam seriam 148 s (**−30% só com o escalonamento**).
- Caminho crítico típico: `profile 4 s → news_30d 34–47 s → sentiment 13–23 s → forecast 17–25 s → rating 43 s`.
  Na CPNG foi `relations 154 s → rating 44 s`: as relações (cache de 30 dias, só contexto) atrasaram tudo em 2 minutos.
- A classificação v2 demora 43 s: skill (2 s) → bull (15 s) → bear (13 s) → juiz (13 s). Bull e bear correm em série.
- Semáforo LLM = 4 com 6 agentes LLM na 2.ª camada (4 notícias + concorrentes + relações): dois ficam à espera.
- Timeouts muito acima do observado: news_30d 1200 s (máx. real 47 s), rating 1500 s (47 s), omissão 900 s.
- Cache de outputs: 23 acertos em 174 nós (13%). `technical`, `forecast_stats` e os `*_lead` expiram em 15–60 min;
  `timing`, `forecast`, `sentiment`, `rating` e `news_4h` nunca fazem cache.
- SQLite: `journal_mode=delete` (sem WAL) nas duas bases; uma ligação nova por comando do bot.

## 7. Falhas e skips gravados (12 em 260)

| Erro | Onde | Estado |
|---|---|---|
| `ValueError: Length of values (70) does not match length of index (53)` | `asia_lead`, `us_lead` (005930.KS) | **por corrigir** — falhou em silêncio; a classificação seguiu sem os sinais entre sessões |
| `DataUnavailable: financials SSU` → `health`, `fundamental_data` falham, `fundamental` skipped | SSU (ADR sem financeiras no yfinance) | sem alternativa de fonte; a classificação saiu "venda forte 0,50" |
| `OperationalError: cannot commit` / `InterfaceError` | `calendar`, `indicators` | corrigido com lock no `Store` (ver PLANO §8) |
| `Credit balance is too low` | `rating` (AAPL 12:58) | resolvido com D21; o erro chegou cru ao utilizador |

No bot, os nós falhados aparecem só como "Sem resultado nesta análise: asia_lead, us_lead", sem motivo nem consequência.

## 8. Bot Telegram

| Medida | Valor |
|---|---|
| Arranque (imports até ao `run_flow`) | 1,5 s (SDK 0,9 s; matplotlib/secções 0,6 s) |
| 1.ª resposta a `/run` | 1 chamada `sendMessage` (< 1 s), texto fixo "demora alguns minutos" |
| Progresso durante a análise | nenhum (3–5 min de silêncio), sem `/cancelar` |
| Cartão depois de a análise acabar | 0,5 s de matplotlib + 1 `sendPhoto`; PNG de 160–175 KB |
| Legenda do cartão | 154–328 caracteres; 7 botões; secções de 60–1 300 caracteres |
| Concorrência | 1 análise de cada vez (`asyncio.Lock`), o 2.º pedido é recusado e perde-se |
| Persistência | nenhuma: se o processo cair a meio, a tarefa desaparece sem aviso |
| Comandos | /run, /detalhe, /ipo, /ipos, /status, /history, /ajuda — sem watchlist, comparação, universo, definições, estado |

## 9. Testes

108 testes unitários, todos a passar em 2,1 s (`python -m unittest discover -s tests -t .`).

## 10. Metas

| Métrica | Baseline (análise fria) | Meta | Como |
|---|---|---|---|
| Tokens por análise | 1,92 M | **≤ 0,75 M (−60%)** | isolar as sessões (secção 4), uma só recolha de notícias, dossier compacto |
| Custo equivalente | 2,50 USD | **≤ 1,10 USD (−55%)** | idem; modelos mais baratos só onde um A/B mostrar o mesmo resultado |
| Tempo real | 211 s | **≤ 140 s (−33%)** | escalonamento por dependências, menos um pedido por agente, bull/bear em paralelo |
| Reanálise no mesmo dia | 130 s / 1,72 USD | ≤ 60 s / ≤ 0,60 USD | cache de nós LLM por conteúdo do input |
| 1.ª resposta do bot | < 1 s, sem progresso | < 2 s, progresso visível a cada nó, `/cancelar` | mensagem de estado editada |
| Falhas silenciosas | 2 tipos conhecidos | 0 | cada falha chega ao utilizador com motivo e consequência |
| Qualidade | AAPL hold; 005930.KS compra; guard 0 por verificar | igual nos 3 tickers de referência | A/B com o mesmo dossier antes de aceitar cada corte |
| Tarefas perdidas num reinício | todas | 0 | fila persistente + retoma |
