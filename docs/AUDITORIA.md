# Auditoria — Agentock (Fase 10)

> 2026-11-15. Cinco auditores independentes em paralelo (dados e cálculos, agentes e prompts, orquestração e
> performance, bot e UX, infraestrutura 24/7) mais a medição do baseline ([BASELINE.md](BASELINE.md)).
> Cada achado tem evidência (`ficheiro:linha` no código de antes da Fase 10, ou output real reproduzido).
> Severidade: crítica / alta / média / baixa. Esforço: S (< 1 h) · M (meio dia) · L (mais).
> A coluna **Estado** é atualizada no fecho: ✅ corrigido com teste · 🟡 parcial · ⏳ pendente (ver PLANO §Pendências).

## Prioridade 1 — críticos (qualidade do resultado, dinheiro, segurança)

| ID | Achado | Sev. | Esf. | Evidência | Estado |
|---|---|---|---|---|---|
| A1 | **Cada sessão LLM leva ~45 mil tokens alheios** (16 tools do Claude Code, skills globais, conectores MCP da conta) e gasta um pedido só para carregar a skill | crítica | S | BASELINE §4; `core/runner.py:139-143` (`allowed_tools` só dá permissão; `setting_sources=["project"]`). Experiência: −88% tokens, −71% custo | ⏳ |
| A2 | **O guard aceita quase qualquer número**: a tolerância de arredondamento não é escalada em `v/100` e `v*100` e compara contra os ~1 700 valores do dossier | crítica | M | `agents/guard_agent/run.py:79-83,101`. No dossier real da Samsung passam 100% dos inteiros 32–999 escolhidos ao acaso e 78% dos `x,xx`. O "35 verificados, 0 por verificar" não provava nada | ⏳ |
| A3 | **`market_share` em cache por indústria serve a análise de outra empresa** | crítica | S | `agents/market_share_agent/agent.yaml` (`cache_key: [profile.industry, profile.sector]`). A Coupang recebeu o retalho desportivo europeu da SSU; a Samsung recebeu "o iPhone é o produto com maior peso na receita da Apple" | ⏳ |
| A4 | **Agentes que leem a web com `Read` sem âmbito e `WebFetch` livre**: uma notícia maliciosa podia mandar ler `.env` e enviá-lo num URL; tools não listadas (`Agent`, `Glob`, `ScheduleWakeup`) foram aceites | crítica | M | `_shared/news_base/agent.yaml:13`, `pre_ipo_agent/agent.yaml:7`; logs: `Glob` e `ScheduleWakeup` no pré-IPO, subagente web-fetch em relations; `block_domains` só vê o `url` do WebFetch (`core/hooks.py:43-53`) | ⏳ |
| A5 | **Londres: preço em pence e contas em libras** → DCF e Altman errados 100× | crítica | S | `fundamental_data_agent/run.py:76,98-100`, `health_momentum_agent/run.py:127-132`. AZN.L: DCF 136,97 (−99%) em vez de 13 697p; Altman Z 264 em vez de ≈ 3,7 | ⏳ |
| A6 | **Arranque do bot repete comandos antigos e duplica análises pagas**; a guarda "já há uma análise" não é atómica | crítica | S | `tools/telegram_bot.py:225` (`offset = 0`), `:110-114`. Simulação: 5 `/run` em simultâneo → 2 análises, 3 pedidos perdidos | ⏳ |
| A7 | **`memory` e `alert` não são idempotentes; a histerese conta execuções** (um retry confirma uma mudança de 1 nível) | crítica | M | `core/db.py:88` (sem UNIQUE em `run_id`), `core/changes.py:50-56` | ⏳ |

## Prioridade 2 — altos

| ID | Achado | Sev. | Esf. | Evidência | Estado |
|---|---|---|---|---|---|
| B1 | Orquestrador por camadas: 211 s reais vs 148 s possíveis; o timeout conta a espera no semáforo; a duração gravada exclui fila e arranque do CLI (2–3 s por sessão) | alta | M | `core/orchestrator.py:139-141`; BASELINE §6 | ⏳ |
| B2 | Quatro agentes de notícias: 0,70 USD e ~1,05 M tokens, 45% de itens repetidos; 30 WebSearch renderam 5 de 103 itens; 26 `check_window` conferiram timestamps que já vinham da API; 29% das sessões acabaram com 0 itens depois de 4–5 pedidos | alta | M | BASELINE §5; 21 sessões transcritas | ⏳ |
| B3 | Dossier de 45 mil caracteres lido 3 vezes; compactável para 25 mil (−45%) sem perder nenhum dos 150 números citados pelo juiz | alta | S | 4 dossiers gravados; tabela manter/resumir/retirar no relatório do auditor (b) | ⏳ |
| B4 | Debate v2 em série (bull → bear → juiz, 8 pedidos, 43 s); o juiz re-lê o contexto em 4 pedidos (141 mil tokens de cache-read no Opus) | alta | M | `rating_agent/prompt.md:5`; sessões do rating | ⏳ |
| B5 | Nós LLM sem cache: reanálise 53 min depois, com a bolsa fechada, refez tudo o que é LLM (130 s, 1,72 USD) | alta | M | `agent_outputs`: 0 acertos em `news_4h`, `sentiment`, `timing`, `forecast`, `rating`; taxa global 13% | ⏳ |
| B6 | `asia_lead`/`us_lead` falham por corrida de threads no `exchange_calendars` | alta | S | `core/sessions.py:22-33`; reproduzido 3 em 3 (`ValueError: Length of values…`) | ✅ |
| B7 | Classes de ações: DCF por ação dividido só por uma classe (GOOGL 283,69 em vez de 135,87; Samsung 71 448 em vez de 62 645) | alta | S | `fundamental_data_agent/run.py:48` | ⏳ |
| B8 | Dívida/capital do Yahoo vem em %; a heurística só divide acima de 10 (Samsung: 2,8% tratado como 2,8× → `health_score` 66 em vez de 83) | alta | S | `health_momentum_agent/run.py:73` | ⏳ |
| B9 | Cotações cruzadas sem validar o nome: Samsung → `NU` (Nu Holdings), CPNG → `AMD`; entram no `us_lead` com peso máximo | alta | S | `profile_agent/run.py:183-190` | ⏳ |
| B10 | Erros do Telegram sem tratamento (429, 400, rede): o cartão pode perder-se depois de a análise estar paga; legenda cortada a 1024 a meio de uma etiqueta | alta | S | `core/telegram.py:34-38,49` | ⏳ |
| B11 | Erros crus chegam ao utilizador (`timeout (240s)`, `DataUnavailable: …HTTPSConnectionPool`, "sem dados de entrada ['decision']" a esconder "Credit balance is too low"); limite de utilização sem causa nem hora de reposição | alta | M | `tools/telegram_bot.py:57,122,178`; `core/runner.py:168-175` | ⏳ |
| B12 | Texto sem "/" é ignorado; `/run Banco Comercial` analisa "Banco"; botões de cartões antigos dão `HTTPError 400`/`KeyError` | alta | S | `tools/telegram_bot.py:112,165,249` | ⏳ |
| B13 | Sem supervisão: a tarefa agendada não existe e a do `install_bot_task.ps1` falharia (`pythonw` → `sys.stdout` é `None`); sem instância única, heartbeat, aviso de arranque/queda, rotação de logs | alta | M | `tools/install_bot_task.ps1:12-13`, `tools/telegram_bot.py:231-238,254` | ⏳ |
| B14 | Os 5 segundos falham: legenda da AAPL "• Fundamentais • Analistas e alvos • Técnica e momentum", sem preço, confiança, o que mudou nem próximo passo; 3–5 min de silêncio | alta | M | `core/messages.py:117`, `core/sections.py:38-39` | ⏳ |
| B15 | Injeção de 2.ª ordem: título e resumo de notícias entram crus no sentimento e no dossier; `tone`/`relevance` vêm do texto da web | alta | M | `sentiment_agent/task.md`, dossier | ⏳ |
| B16 | Avaliação (Fase 7): preço de entrada contra barras ajustadas a splits; base do índice é o fecho e a da ação é intradiária; índice em falta vira excesso = retorno bruto; sem deduplicação (AAPL 5× num dia) | alta | M | `tools/evaluation.py:44,71,130,131` | ⏳ |

## Prioridade 3 — médios

| ID | Achado | Sev. | Esf. | Evidência | Estado |
|---|---|---|---|---|---|
| C1 | Guard: `mi` casa com "mil" (×1e6) e `tri` com "trimestres"; `1.5B`, `2,66x` não são tokenizados; datas nunca conferidas; `bull_case`/`bear_case` não conferidos | média | S | `guard_agent/run.py:10-14,96,136` | ⏳ |
| C2 | Múltiplos negativos entram nas comparações (CPNG EV/EBITDA −68 → "desconto" de −686%) | média | S | `fundamental_data_agent/run.py:87`, `comps_agent/run.py:45` | ⏳ |
| C3 | Pausa de almoço (HK, Tóquio) tratada como fechado desde a véspera | média | S | `core/sessions.py:28-32` | ⏳ |
| C4 | Dívida líquida ignora investimentos de curto prazo (Samsung −32,6 em vez de −100,6 biliões KRW) | média | S | `providers/yfinance_p.py:30` | ⏳ |
| C5 | Mistura de anual com 12 meses móveis sem rótulo; DCF parte do FCF do último exercício | média | M | outputs gravados da Samsung | ⏳ |
| C6 | Piotroski "sem diluição" falha por ruído no n.º de ações (Samsung 6 em vez de 7) | média | S | `health_momentum_agent/run.py:35` | ⏳ |
| C7 | Intervalos lognormais: o "p50" a 12 meses fica 25% abaixo do preço (vol. 77%) e é lido como cenário central; arredondamento a 2 casas zera penny stocks | média | S | `forecast_stats_agent/run.py:21` | ⏳ |
| C8 | Sinais entre sessões: a referência do proxy pode ser de 11 h antes do fecho da ação (informação contada duas vezes) | média | M | `core/sessions.py:46-50` | ⏳ |
| C9 | TTL e chaves de cache desalinhados: `technical` 1 h com chave diária; `forecast_stats` com `profile.price` nunca acerta; `fundamental_data` com o `comps` inteiro; scripts puros com cache só acrescentam dados velhos | média | S | `agents/*/agent.yaml`; taxa de acerto por nó | ⏳ |
| C10 | `comps` em série: 15,8 s a frio para 8 peers, 4,8 s com 8 threads | média | S | `comps_agent/run.py:58-70` | ⏳ |
| C11 | SQLite sem WAL (cada `persist` 3,9 ms no event loop), `connect()` corre schema e migrações por chamada, caches nunca limpas, sem índices para o bot | média | S | `core/db.py:77-85`, `core/data/store.py` | ⏳ |
| C12 | Timeouts 20–30× acima do observado; `wait_for` sobre thread não a pára | média | S | `flow.yaml` (news_30d 1200 s vs 47 s; rating 1500 s vs 47 s) | ⏳ |
| C13 | Quota do yfinance falha em vez de esperar (2 análises em paralelo passam os 60/min) | média | S | `core/data/router.py:85` | ⏳ |
| C14 | Um run interrompido não se retoma: repaga ~1,3 USD de nós LLM | média | M | `core/orchestrator.py:124` | ⏳ |
| C15 | Cartão ilegível na bolha do chat (letra efetiva 3,6–5,4 pt); título é o ticker; casos-limite (SSU com eixo "0,00" ×5, sem alvos, < 6 meses) | média | M | `core/charts.py:41-44,62,114-120,130,150,167` | ⏳ |
| C16 | Formatos: três convenções de milhares, rodapé em UTC, "HOLD" em inglês, `/history` sem hora, jargão sem explicação, markdown cru nos cenários | média | S | `core/messages.py:30-33`, `core/charts.py:276`, `core/sections.py:123` | ⏳ |
| C17 | Paredes de texto (`/ipo_ANT` 4 226 caracteres) e botões vazios (Insiders "não analisado" em 6 de 6) | média | S | `core/sections.py:17-19` | ⏳ |
| C18 | Validação de input: sem limite de tamanho; `a:b`/`a*b?` → `OSError` com o caminho local na mensagem; o argumento cru entra no `run_id` | média | S | `tools/telegram_bot.py:112,178`, `core/runner.py:72-74` | ⏳ |
| C19 | Cartão em duplicado quando há alteração (o nó `alert` envia um e o bot outro) | média | S | `change_alert_agent/run.py:57`, `telegram_bot.py:125` | ⏳ |
| C20 | Dependências por fixar (`claude-agent-sdk`, `pydantic`, `pyyaml`, `python-dotenv`) | média | S | `requirements.txt:1-4` | ⏳ |
| C21 | Sem cópias de segurança de `agentock.db` nem limpeza de `data/` | média | S | — | ⏳ |
| C22 | Sentimento: a rubrica é aritmética; recalculada em Python dá o mesmo que o LLM nos 4 dossiers (diferença ≤ 0,04) | média | S | sessões do `sentiment_agent` | ⏳ |
| C23 | Concorrentes e relações: 8–10 `profile` por sessão e 4–6 `quote` que o código podia fazer; na CPNG um subagente web-fetch leu o 10-K (316 mil caracteres, 154 s) | média | M | logs e sessões | ⏳ |
| C24 | Modelos: timing (170–345 tokens de thinking, limiares explícitos) e forecast são candidatos a Sonnet | média | S | sessões Opus | ⏳ |

## Prioridade 4 — baixos

| ID | Achado | Estado |
|---|---|---|
| D1 | Bollinger com desvio-padrão amostral (bandas 2,6% mais largas) — `technical_indicators_agent/run.py:70` | ⏳ |
| D2 | Só o chat é validado, não o remetente (`from.id`); num grupo qualquer membro comandaria | ⏳ |
| D3 | Chaves de fornecedores em query strings; 300 caracteres do corpo do erro vão para a base e para o Telegram (`core/data/http.py:49-59`) | ⏳ |
| D4 | `core/env.py:19` não retira `ANTHROPIC_AUTH_TOKEN` (tem precedência sobre a subscrição) | ⏳ |
| D5 | Prompts: vírgula decimal nem sempre respeitada (technical 49 de 89 números com ponto); rubrica cita `competitors` que não existe no dossier; `NewsReport` obriga a repetir 4 campos | ⏳ |
| D6 | `max_turns` muito acima do observado (notícias 25–30 vs 11–15) e abaixo no `competitors` (20 vs 21) | ⏳ |
| D7 | Altman sempre na variante de 1968 (financeiras só com nota); "WACC" é o custo do capital próprio | ⏳ |

## Verificado e correto (com a referência usada)

RSI14 de Wilder (implementação própria, 005930.KS 42,03 = 42,03) · ATR14 (13 496,18) · MACD 12/26/9 · SMA 20/50/200 e EMA20
(numpy) · retornos a 21/63/252 sessões · volatilidade anualizada (log-retornos, ×√252: 77,09) · quantis lognormais
(E[S]=S₀) · aritmética do Altman Z (Samsung 8,33 à mão; AAPL 13,15 vs 13,16 do FMP) · 8 dos 9 critérios de Piotroski ·
conversão CNY→HKD e rácio ADR (9988.HK 129,54 HKD × 8 ÷ 7,845 ≈ BABA 132,42 USD) · dividend yield a 12 meses · CAGR
(base negativa → `None`) · horário de verão em XNYS · queries SQL parametrizadas · token do Telegram não aparece em
exceções nem no histórico git.

Os valores "implausíveis" da Samsung (P/E forward 2,66, ROE 41,58%, potencial 130,9%) são os do Yahoo e são coerentes
entre si; o dividendo de 8,93% era o Yahoo a anualizar o último pagamento (a 12 meses dá 2,87%; já corrigido no commit
`74abeb7`).

## Avaliado e não adotado

| Ideia | Porquê não |
|---|---|
| Fazer o debate v2 só quando a v1 fica perto da fronteira | Com o debate em nós paralelos e sessões isoladas, a v2 deixa de custar 0,60 USD; o ganho não paga o risco de mudar o padrão D7 nem a perda de comparabilidade na Fase 7 |
| Orçamento "suave" por nó (a classificação segue sem o nó atrasado, que acaba em segundo plano) | Timeouts duros dimensionados pelo observado dão o mesmo teto com muito menos complexidade; um nó que excede o tempo já vira lacuna declarada |
| Prioridades no semáforo LLM | Com uma só recolha de notícias deixa de haver 6 nós LLM a disputar 4 vagas no arranque |
| Chamar a API diretamente nos nós sem tools (poupa 2–3 s de arranque do CLI por sessão) | Exigiria API key: contraria a D21 (autenticação pela subscrição) |

## Por verificar (fora do orçamento desta auditoria)

NVDA: Altman próprio 52,4 vs 30,65 do FMP e Piotroski 4 vs 6 · `calendar_agent`, `analysts_agent`, `deal_math.py`,
`keyed.py`, `regulators.py` linha a linha · respostas reais do Telegram a 429/409 · tamanho da letra do cartão num
telemóvel real · comportamento com login do Claude expirado · S4U com a CLI embutida · preços atuais de alojamento.
