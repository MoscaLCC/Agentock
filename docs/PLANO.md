# Plano de implementação — Agentock

> Estado em 2026-11-15 (rev. 8 — fases 0–9 feitas; **Fase 10: de protótipo a produto**, medida antes e depois). Documento vivo.
> Medições: [BASELINE.md](BASELINE.md) · achados e estado de cada um: [AUDITORIA.md](AUDITORIA.md).

## 0. Estado

| Fase | Estado | Evidência |
|---|---|---|
| 0 — Verificações e fundações | ✅ | cobertura de 13 fontes testada; Telegram; git |
| 1 — Motor | ✅ | router de dados (13 fornecedores), orquestrador DAG, cache, hooks, tools `market` |
| 2 — Fatia vertical (M1) | ✅ | AAPL (v1) e 005930.KS (v2, debate) classificadas e gravadas; alerta real no Telegram (`tools/test_alert.py`) |
| 3 — Dados restantes | ✅ | 9988.HK: sinais entre sessões aplicáveis (BABA + futuros após o fecho de HK), Piotroski/Altman, DCF com conversão CNY→HKD |
| 4 — Notícias e sentimento | ✅ | 4 janelas (4h/24h/7d/30d) + sentimento correram para AAPL |
| 5 — Análise competitiva | ✅ | AAPL: peers validados (GoerTek rejeitada como fornecedora), comps, quotas IDC, 19 subsidiárias do Exhibit 21 |
| 6 — Síntese completa | ✅ | AAPL com os 29 nós: **hold, confiança 0,60 (v2)**; o guard verificou 35 números citados, 0 sem correspondência; debate bull/bear com subagentes |
| 6b — IPOs | ✅ | `ipo_web_agent` encontrou um IPO em Tóquio (Mitsubishi UBE Cement); pré-IPO da Anthropic: S-1/A via SEC, `deal_math` (916 mil M–1,02 biliões USD), peers, janela de IPOs de IA, debate → **neutro 0,50**; MUCC sem prospeto → **neutro 0,35** com 15 campos "não divulgado" (não estimou); alertas Telegram enviados |
| 7 — Avaliação | ✅ código | backfill + relatório; precisa de tempo: N ≥ 30 classificações com 30 dias |
| 8 — Universo e escala | ✅ | top 500 em ~8 s, 18/18 megacaps de referência, estimativa de custo antes de correr |
| 9 — Bot Telegram + histórico | ✅ | substituído pelo bot da Fase 10d |
| 10a — Medição e auditoria | ✅ | `tools/measure.py`, `tools/replay.py`; 5 auditores independentes; 54 achados priorizados (39 corrigidos, 8 parciais, 7 pendentes) |
| 10b — Custo, tokens e tempo | ✅ | análise fria: **2,50 → 0,61 USD, 1,92 M → 0,23 M tokens, 211 → 73 s**; mesma classificação nos 3 tickers de referência |
| 10c — Bugs e cálculos | ✅ | guard por campo, pence em Londres, classes de ações, corrida de threads, cache de outra empresa, idempotência; fórmulas com testes contra referências |
| 10d — Telegram-first | ✅ | fila persistente, progresso editado, /cancelar, /estado, lista, comparação, universo, agendamentos; supervisor e vigia |
| 10e — Alojamento 24/7 | 🟡 | supervisor a correr; falta a tua decisão (Pendências 1–2) |

**245 testes unitários** (`python -m unittest discover -s tests -t .`, 18 s) + testes reais (`tools/smoke_data.py`, `tools/probe_*.py`).

### Antes e depois da Fase 10 (análise fria, dados reais)

| | Antes (média de 4) | Depois | Variação |
|---|---|---|---|
| Tokens por análise | 1,92 M | 0,23 M (AAPL 245 mil · 9988.HK 225 mil · 005930.KS 230 mil) | **−88%** |
| Custo equivalente | 2,50 USD | 0,61 USD | **−76%** |
| Tempo real | 211 s | 73 s (AAPL 75 s · 9988.HK 71 s); 005930.KS 151 s quando a DART está fria | **−65%** |
| Reanálise no mesmo dia | 130 s · 1,72 USD | 76 s · 0,44 USD (só refaz notícias e o que depende delas) | −42% · −74% |
| Turnos LLM | 99 | 42–45 | −56% |
| Classificação | AAPL hold 0,60 · 005930.KS compra 0,55 · 9988.HK hold (v1) | AAPL hold 0,60 · 005930.KS compra 0,55 · 9988.HK hold 0,50 | igual |
| Guard | "35 números, 0 por verificar" (aceitava quase qualquer número) | 19–24 números, ≥ 95% confirmados no campo de origem | passou a discriminar |
| Testes | 108 | 245 | +137 |

### Pendências

**Precisam de uma decisão tua** (dinheiro, contas ou onde isto corre):
1. **Arranque automático.** O bot está a correr com o supervisor (`tools\run_bot.cmd`), mas só até fechares a sessão.
   Para ficar sempre ligado: `powershell -ExecutionPolicy Bypass -File tools\install_bot_task.ps1` (regista o supervisor e
   a vigia do sinal de vida; não precisa de administrador; remove-se com `-Remove`).
2. **Alojamento 24/7** (D36): recomendo ficar no PC atual com essa tarefa. Para arrancar sem sessão iniciada é preciso
   um token de longa duração (`claude setup-token` → `CLAUDE_CODE_OAUTH_TOKEN` no `.env`) e registar a tarefa como
   administrador; não testado. Um mini-PC dedicado é o passo seguinte se a disponibilidade não chegar.
3. **Análises automáticas da lista** (`/alertas` no bot): desligadas por omissão, porque cada uma gasta ~0,6 USD
   equivalentes da subscrição. Liga-as tu, com o custo à vista.
4. **Modelos**: timing e forecast (Opus) são candidatos a Sonnet; falta o A/B com os inputs gravados
   (`python tools/replay.py RUN_ID timing --model claude-sonnet-5-5`), ~0,05 USD por comparação.

**Por fazer (com o porquê)**:
5. Fluxos de IPOs (`ipos`, `ipo`): herdaram o isolamento das sessões e os hooks novos, mas **não foram revalidados com
   execuções reais** (o pré-IPO custa 1,1–1,4 USD e não fazia parte dos 3 tickers de referência).
6. Auditoria, ainda abertos: C5 (rácios anuais vs 12 meses móveis), C8 (referência antiga nos sinais entre sessões),
   C13 (esperar pela quota do yfinance em vez de falhar), C23 (validação de concorrentes/relações em código), D3 e D7.
   Estão descritos em [AUDITORIA.md](AUDITORIA.md); nenhum é crítico.
7. Fase 7: o relatório só é fiável com N ≥ 30 classificações avaliadas a 30 dias — `--backfill` e `--eval` periodicamente.
8. Um `timeout` não pára uma thread de script nem garante a morte do processo do agente (o nó é dado como falhado e a
   análise segue); os tetos atuais (≤ 300 s) limitam o efeito.
9. GuruFocus sem acesso à API (desligado); cobertura de IPOs fora dos EUA depende da pesquisa web.

---

## Como usar

**No dia a dia: pelo Telegram** (o bot arranca com `tools\start_bot.cmd` ou, de forma permanente, com a tarefa agendada).

| No Telegram | O que faz | Custo |
|---|---|---|
| `AAPL`, `Samsung` ou `/analisar AAPL [v1\|v2]` | análise completa: veredicto em texto (≤ 350 caracteres) + cartão com botões | ~0,6 USD · ~75 s |
| `/hoje` · `/lista` · `/seguir X` · `/deixar X` | a tua lista e o resumo do dia | grátis |
| `/comparar A B` · `/historico X` · `/detalhe X` | sobre análises já feitas | grátis |
| `/ipos` · `/ipo X` · `/universo N` | IPOs; as N maiores (mostra o custo e pede confirmação) | variável |
| `/alertas` · `/definicoes` | análises automáticas, resumo diário, v1/v2 | — |
| `/estado` · `/cancelar` · `/ajuda` | fila, utilização de hoje, última cópia; parar a análise em curso | grátis |

**Pela linha de comandos** (manutenção e medição):
```
python flow.py AAPL                     # análise completa (aceita nome "Samsung" ou código "005930")
python flow.py AAPL --rating v1         # classificação sem debate (v2 é o padrão)
python flow.py AAPL --run-id RUN_ID     # retoma uma análise interrompida sem repetir os nós já feitos
python flow.py AAPL --dry-run           # DAG · --verbose: output de todos os nós · --no-cache
python flow.py --ipos | --ipo "Nome"    # IPOs
python flow.py --universe --top 50      # universo + estimativa de custo; --yes para correr
python flow.py --backfill && python flow.py --eval
python tools/measure.py                 # custo, tempo e tokens por análise e por nó (dados gravados)
python tools/replay.py RUN_ID NÓ [--model M] [--chain]   # repete um nó com os mesmos dados (A/B)
python -m unittest discover -s tests -t .
```
Custo equivalente observado (o que custaria em créditos da API; com a subscrição não é faturado, mas conta para os
limites de utilização): análise fria ~0,6 USD (era ~2,5); reanálise no mesmo dia ~0,4 USD; pré-IPO 1,1–1,4 USD (não remedido).

---

## Decisões

| # | Decisão | Porquê |
|---|---|---|
| D1 | Trigger manual: ticker, `--universe`, `--ipos`, bot Telegram | pedido do utilizador |
| D2 | Uma ação de cada vez por omissão; universo com estimativa de custo e `--yes` | custo |
| D3 | Código onde os dados são estruturados; LLM só para interpretar/sintetizar | qualidade verificável, custo |
| D4 | Alertas por Telegram | pedido do utilizador |
| D5 | yfinance principal; FMP complemento só EUA/ADRs | cobertura verificada |
| D6 | A classificação anterior NÃO entra na classificação nova; estabilidade pela histerese; diff de razões no alerta | independência para a avaliação |
| D7 | **Classificação v2 (debate bull/bear) é o padrão**; v1 disponível (`--rating v1`) e gravada com a versão | qualidade; comparação na Fase 7 |
| D8–D9 | `asia_lead_agent`; mercados EUA, Europa, Japão, China, HK, Coreia (+ resto do mundo no universo) | pedido do utilizador |
| D10–D11 | SEC (User-Agent) e OpenDART ligados | documentos oficiais |
| D12 | 11 fornecedores complementares atrás do router com quotas | redundância, validação cruzada |
| D13 | IPOs: módulo próprio (calendário, pré-IPO com classificação própria, ciclo pós-IPO) | uma empresa pré-IPO não cabe no fluxo por ticker |
| D14 | Horários/feriados via `exchange_calendars` | verificado, com DST e pausas |
| D15 | akshare só secundária | o Eastmoney limita o IP |
| D16 | **Guard anti-alucinação é um nó de script**, não um hook | os hooks só veem tool calls, não a resposta final |
| D17 | Peers: o LLM propõe, as tools validam, o script compara (subagentes ficam para o debate) | determinístico e auditável |
| D18 | Máx. 4 agentes LLM em paralelo (`AGENTOCK_LLM_PARALLEL`) | limites da API |
| D19 | Universo: cotação principal = a de **maior liquidez** (valor negociado/dia em USD) | a pontuação por moeda escolhia APC.DE em vez de AAPL e ADRs/locais mal |
| D20 | GuruFocus por `requires_env` (MCP condicional) | o token existe mas não tem acesso à API |
| D21 | **Agentes LLM autenticados pela subscrição do Claude Code** (`AGENTOCK_CLAUDE_AUTH=subscription`): o Agentock retira a `ANTHROPIC_API_KEY` só do seu processo; `api` volta aos créditos | créditos da API esgotados; decisão do utilizador. A variável do Windows não foi apagada para não afetar outros programas |
| D22 | **Insiders por script, sem LLM** (`insiders_agent`, 2.20): só compras/vendas em bolsa contam; vendas em plano 10b5-1 (ou com pré-aviso na Coreia) pesam pouco; score −2…+2 por regras explícitas (compra em grupo ≥ 3 insiders em 30 dias +2; gestão de topo ≥ 100 mil USD ou compras ≥ 0,01% da market cap +1; vendas discricionárias ≥ 0,1% da market cap ou ≥ 3 vendedores −1; ≥ 0,5% −2). Fontes: SEC Form 4 (EUA) → Finnhub; DART (Coreia); restantes mercados `available: false`. O sentimento recebe este resultado em vez de chamar `mcp insider` | dados estruturados → código verificável e testado; menos tokens; o MSPR da Finnhub mistura vendas planeadas e atribuições |
| D23 | **Coreia: motivo lido do documento DART**, não só do resumo `elestock` (variação líquida). Os 80 relatórios com mais ações por 180 dias são lidos (cache em disco, um relatório entregue não muda); 장내매수/매도 → P/S; 수증/증여/상속/상여/스톡옵션 fora do sinal; **장외 (fora de bolsa) fora do sinal** | Samsung: as 18,8 M ações de 이재용 em out–nov 2026 eram uma doação e uma compra fora de bolsa à mãe, não compras em bolsa — o resumo dava "positivo" por engano |
| D24 | **Sessões LLM isoladas**: `tools=` só as declaradas, `skills=[]`, `strict_mcp_config`, sem settings do projeto, sem memória nem título de sessão, `permission_mode=dontAsk`; o guia (skill) de cada agente vai colado no system prompt; sem cache de prompt nos agentes de um só pedido | cada sessão herdava ~45 mil tokens alheios (16 tools do Claude Code, skills globais, conectores MCP da conta) e gastava um pedido só para carregar a skill; medido no timing (Opus): 0,306 → 0,069 USD com a mesma conclusão. Tira também os conectores pessoais do alcance de agentes que leem a web |
| D25 | **Notícias numa só recolha**: `news_feed` (código: APIs, sem repetidos, id estável) → `news_scan` (1 sessão: triagem + pesquisa web local e do último mês) → `news` (código: janelas 4h/24h/7d/30d sem sobreposição, recalculadas pela hora de publicação; o que saiu depois da triagem entra "por triar") | 4 agentes custavam 0,70 USD e ~1,05 M tokens com 45% de itens repetidos; agora ~0,09 USD. A janela de 4 h nunca fica velha sem pagar outra sessão |
| D26 | **Debate v2 em nós do DAG**: `bull` e `bear` em paralelo (Sonnet, um pedido cada) sobre o dossier compacto → juiz (Opus, um pedido, com os dois casos). A v2 continua a ser o padrão (D7). Fazer o debate só "perto da fronteira" foi avaliado e **não adotado** | o juiz relia o contexto em 4 pedidos e os subagentes liam um ficheiro de 50 mil caracteres: 0,60 → 0,18 USD e 43 → 26 s, com a mesma classificação em 4 dossiers gravados. Com este custo, condicionar o debate não paga o risco nem a perda de comparabilidade na Fase 7 |
| D27 | **Dossier compacto feito por código** (`core/dossier.py`): sai o que não sustenta uma razão (metadados, fontes, prosa que repete números); lacunas ficam `null` | 45 mil → 24 mil caracteres sem perder nenhum dos números citados; é exatamente o que o guard confere |
| D28 | **Sentimento por código** (`core/sentiment.py`); nenhum item pesa mais de 35% | a rubrica é aritmética: dava o mesmo que o LLM nos dossiers gravados (diferença ≤ 0,04) e saía do caminho crítico (13–23 s); o teto limita o efeito de uma notícia falsa de fonte única |
| D29 | **Guard por campo**: o juiz indica em `evidence` o caminho de cada número; o guard confere contra esse campo, com tolerância só de arredondamento; ÷100 só com "%"; datas conferidas; `bull_case`/`bear_case` incluídos | a versão anterior aceitava ±1,1% e ×100/÷100 contra ~1 700 valores: números ao acaso passavam quase sempre. Os resultados do guard de antes e depois **não são comparáveis** |
| D30 | **Orquestrador por dependências**, com `when:` (nó desligado ≠ falha), progresso, cancelamento e retoma (um nó só se reaproveita se as suas dependências também o foram); timeouts ≈ 3× o observado. Orçamentos "suaves" por nó avaliados e **não adotados** | por camadas eram 211 s reais para 148 s possíveis; um teto duro dá o mesmo limite com muito menos complexidade |
| D31 | **Cache de nós LLM pelo conteúdo do input** (sem campos voláteis); scripts puros sem cache de nó; `market_share` por empresa | reanálise sem mudanças não volta a pagar; a cache por indústria servia à Coupang a análise da SSU |
| D32 | **Histerese exige outra análise**: a confirmação de uma mudança de 1 nível tem de vir ≥ 4 h depois; `memory` e `alert` são idempotentes por `run_id` | um retry ou uma reanálise em cache confirmavam a mudança e duplicavam o histórico |
| D33 | **Bot com fila persistente** (SQLite), um worker, uma mensagem de progresso editada; comandos escritos com o bot desligado e texto livre pedem confirmação; análises automáticas desligadas por omissão | nada se perde num reinício; nenhuma análise paga corre sem o dono a ver o custo |
| D34 | **Formatos**: milhares com ponto (1.234,56), hora de Lisboa, "Manter" em vez de "Hold", sinal de menos tipográfico | pedido do utilizador; havia três convenções na mesma conversa |
| D35 | **Agentes que leem a web não têm `Read` nem `Bash`**; `fetch_guard` (sem endereços internos nem URLs longos) e `read_guard` (só a pasta do agente) sempre ligados; recusas registadas; texto externo marcado como dados | uma notícia maliciosa podia mandar ler `.env` e enviá-lo num URL |
| D36 | **Alojamento: PC atual + supervisor + tarefa agendada** (recomendação; decisão do utilizador pendente). Mini-PC dedicado se a disponibilidade não chegar; VPS e containers não compensam | custo zero, o PC não adormece, a subscrição serve o uso individual; em API seriam ~90 USD/mês a 5 análises por dia |
| D37 | **Moeda principal vs subunidades**: preço como cotado (pence em Londres), contas e market cap na unidade principal (`core/util.major_currency`); valor por ação com market cap ÷ preço | DCF e Altman erravam 100× em Londres; `sharesOutstanding` é só uma classe (GOOGL, Samsung) |
| D38 | **Intervalos estatísticos com a mediana no preço atual** | com volatilidade alta, a mediana "sem drift" ficava 25% abaixo do preço e era lida como cenário central |

---

## 1. Princípios
1. Números vêm de código; o LLM interpreta e cita — o guard verifica cada número citado.
2. Contratos JSON (pydantic) entre agentes; tudo gravado (`agent_outputs`).
3. Falha isolada: nós dependentes de um nó falhado ficam `skipped`; inputs opcionais seguem como `null` (lacuna).
4. Cache por âmbito (`cache_key` com caminhos, ex.: `profile.symbol`, `profile.industry`).
5. Fontes grátis são frágeis → cache, quotas, retries, fonte alternativa por dado.
6. Medir tudo: custo, tempo, acerto.

---

## 2. Arquitetura (fluxo `ticker`, 32 nós — `python flow.py AAPL --dry-run`)

Cada nó arranca quando as **suas** dependências terminam (D30). LLM = sessão isolada (D24).

```
profile
├─ dados (código, em paralelo): indicators · health · analysts · price_targets · calendar · ipo_lifecycle · insiders
│                               asia/europe/us_lead · fundamental_data · forecast_stats · comps
├─ notícias: news_feed (código) → news_scan (LLM, 1 sessão) → news (código) → sentiment (código)
├─ contexto (LLM): competitors → market_share · relations
└─ leituras (LLM): technical · fundamental · timing · forecast
        ↓
dossier (código, compacto) → bull ∥ bear (LLM) → rating (juiz, LLM) → guard (código) → memory → alert
```
11 sessões LLM por análise fria (eram 13 + 2 subagentes), 8 delas de um só pedido.
Fluxos `ipos` (ipo_web → ipo_calendar) e `ipo` (pre_ipo → ipo_memory).

**Bot** (`tools/telegram_bot.py`): `poll` (Telegram) → tarefa em `jobs` (SQLite) → `worker` (uma de cada vez) →
`run_flow` com progresso/cancelamento → veredicto + cartão. `scheduler`: sinal de vida, resumo diário, análises
automáticas, cópia e limpeza às 03:00. Supervisor: `tools\run_bot.cmd`; vigia: `tools\bot_watchdog.py`.

---

## 3. Fontes de dados (router `core/data`, config `config/data_sources.yaml`)

| Fornecedor | Cobre (verificado) | Papel |
|---|---|---|
| yfinance | global: preços, intraday, perfil, notícias, analistas, alvos, calendário, financeiras, pesquisa, câmbios, screener | principal |
| FMP (grátis) | EUA: perfil, alvos, grades, peers, scores, DCF | complemento EUA |
| Finnhub | EUA: notícias, recomendações, insiders, calendário de IPOs | notícias/insiders/IPOs |
| Alpaca | EUA: cotação tempo real, notícias | tempo real |
| Tiingo | EUA + China A: EOD; intraday IEX | 2.ª fonte EOD China |
| iTick | Ásia: cotação + intraday | 2.ª fonte Ásia |
| EODHD | global EOD, notícias (20/dia) | validação cruzada |
| Twelve Data | câmbios, EUA | câmbios |
| Alpha Vantage | IPOs (CSV), EOD | último recurso |
| Marketstack | EUA EOD | último recurso |
| akshare | China: notícias Eastmoney | China (secundária) |
| SEC EDGAR | EUA/ADRs: filings, Exhibit 21/8, pesquisa de prospetos, lock-up do 424B4, **Form 4 (insiders, com cargo e plano 10b5-1)** | documentos oficiais |
| OpenDART | Coreia: comunicados, **participações de executivos e grandes acionistas (elestock + documento com o motivo)** | documentos oficiais |

Capacidades: quote, eod, intraday, profile, news (merge), analyst_recs, price_targets, upgrades, peers, calendar, search, fx,
ipo_calendar (merge), financials, scores, dcf, insider, insider_transactions, filings, subsidiaries, sec_search, lockup.
Validação cruzada: Piotroski e Altman próprios = FMP na AAPL (9 = 9; 13,15 vs 13,16); fechos iguais entre 2 fontes.

---

## 4. Mercados (horários via `exchange_calendars`, UTC)

| Bolsa | Inverno | Verão | Pausa |
|---|---|---|---|
| XNYS | 14:30–21:00 | 13:30–20:00 | — |
| XETR/XAMS/XLON/XSWX | 08:00–16:30 | 07:00–15:30 | — |
| XTKS | 00:00–06:30 | idem | 02:30–03:30 |
| XKRX | 00:00–06:30 | idem | — |
| XHKG | 01:30–08:00 | idem | 04:00–05:00 |
| XSHG (também Shenzhen) | 01:30–07:00 | idem | 03:30–05:00 |

Limites diários tratados: China ±10% (±20% STAR/ChiNext), Coreia ±30%.

---

## 5. Catálogo de agentes (36)

S = script · L = LLM (modelo) · artefactos: sk skill, sc script, sub subagentes, tp template, mcp tools do router

| # | Agente | Tipo | Artefactos | Cache |
|---|---|---|---|---|
| 0.1 | universe_agent | S | config/universe.yaml | 1 dia |
| 0.2 | profile_agent | S | — | (router) |
| 2.1 | news_feed_agent → news_scan_agent → news_agent (D25) | S → L sonnet → S | `core/news.py`; WebSearch/WebFetch só no scan | 10 min / 1 h / — |
| 2.5a/2.5/2.6 | asia/europe/us_lead (base `_shared/lead_base`) | S | core/sessions.py | 15 min |
| 2.7 | health_momentum_agent | S | — | 12 h |
| 2.8a / 2.8 | technical_indicators_agent / technical_agent | S / L haiku | sk technical-reading | 1 h |
| 2.9a / 2.9 | fundamental_data_agent / fundamental_agent | S / L sonnet | sk fundamental-framework | 12 h |
| 2.10 | sentiment_agent (D28) | S | `core/sentiment.py` (rubrica em código; recebe notícias, analistas e insiders) | — |
| 2.11 | market_share_agent | L sonnet | sk market-structure | 30 dias, **por indústria** |
| 2.12a / 2.12b | competitors_agent / comps_agent | L sonnet / S | sk peer-selection, mcp peers/search/profile | 7 dias / 1 dia |
| 2.13 | relations_agent | L sonnet | sk relations-sources, mcp subsidiaries/filings | 30 dias |
| 2.14 | calendar_agent | S | — | 6 h |
| 2.15 | timing_agent | L opus | sk timing-rules | — |
| 2.16 / 2.17 | analysts_agent / price_targets_agent | S | — | 6 h |
| 2.18a / 2.18 | forecast_stats_agent / forecast_agent | S / L opus | sk scenarios | — |
| 2.19 | dossier_agent → debate_bull/bear_agent → rating_agent (v2) / rating_v1_agent (D26, D27) | S → L sonnet ×2 → L opus | `core/dossier.py`, guia rating-rubric, `evidence` por número | 6 h, por conteúdo |
| 2.20 | insiders_agent | S | core/data/insiders.py (parsers Form 4 e DART), regras D22; cartão (barra) + botão 👔 Insiders | 6 h |
| — | guard_agent (D29) | S | números por campo e por valor, multiplicadores PT/EN, datas | — |
| 3 / 4 | memory_agent / change_alert_agent | S | diff de razões | — |
| I.1 | ipo_web_agent + ipo_calendar_agent | L sonnet + S | — | 12 h |
| I.2 | pre_ipo_agent | L opus | sk pre-ipo-analysis, sc deal_math, sub bull/bear, mcp sec_search… | 1 dia |
| I.3 | ipo_lifecycle_agent | S | lock-up do 424B4 (SEC) | 12 h |
| — | ipo_memory_agent / eval_agent | S | tp report.md | — |

---

## 6. Transversal
- Modelos: Haiku 5.5 (leitura técnica), Sonnet 5.5 (notícias, análise, subagentes), Opus 5.5 (timing, forecast, classificação, pré-IPO). `max_budget_usd` por agente.
- Observabilidade: `data/logs/<run_id>.jsonl` (cada tool call), `agent_outputs` (custo, duração, turnos), `data/runs/<run_id>/` (inputs em ficheiro).
- Segurança: `.env` fora do git; bot só responde ao dono; sessões isoladas (D24); `fetch_guard`, `read_guard`,
  `block_domains` (D35); registo do bot sem segredos; versões fixadas em `requirements.txt`.
- Dados: SQLite em WAL; cópia diária de `agentock.db` em `data/backups/` (14 dias); limpeza de caches, logs e
  execuções com mais de 30 dias (o histórico `runs` nunca se apaga).
- Guardrails: aviso "não é aconselhamento financeiro" em todos os alertas e relatórios.

## 7. Riscos
| Risco | Mitigação |
|---|---|
| Créditos/limites da API LLM | `max_budget_usd`, semáforo LLM, estimativa antes do universo, falha isolada |
| yfinance partido/limitado | router com alternativas, cache, isolamento em `core/data` |
| Buracos do screener (ex.: Moutai ausente) | megacaps de referência acrescentadas pelo router (`injected`) |
| Notícias/números inventados | check_window, guard, fontes nas saídas |
| Peers com ruído | validação por tools + `rejected_hints` |
| Sinais entre sessões fracos | `applicable: false`; medir na Fase 7 |

## 8. Bugs encontrados e corrigidos (para não repetir)
- `return` dentro do `async for` do SDK → `RuntimeError: aclose()`; consumir o gerador até ao fim.
- `.gitignore` com `data/` escondia `core/data/`; usar `/data/`.
- SQLite partilhado entre threads → `InterfaceError`; lock no `Store`.
- YAML: a chave `no` (Noruega) é lida como `False`; pôr entre aspas.
- `IntEnum` com valor 0 (Hold, Neutro) é "falsy"; comparar com `is None`.
- `cache_key` com o perfil inteiro nunca acertava (o preço muda); usar caminhos (`profile.symbol`).
- Input `run_id` colidia com o argumento do `run_agent`; inputs passam como dicionário.
- Universo: escolha da cotação principal por moeda falhava (APC.DE, ADRs); passou a ser por liquidez.
- SEC: a lista de entregas de uma empresa inclui os Form 4 em que ela é a **declarante** noutra empresa (ex.: Berkshire como acionista da OXY) → filtrar por `issuerCik`.
- DART `elestock` dá só a variação líquida: um aumento de 11 M ações era uma doação (수증) → ler o motivo no documento do relatório (D23).
- Cache em disco de dados derivados: guardar o dado bruto (o motivo) e recalcular o código ao ler, para uma correção do mapeamento valer também para a cache.
- A cache de um nó por **indústria** servia a análise de outra empresa (Coupang recebia a da SSU): chave por empresa.
- `exchange_calendars` não é thread-safe ao construir um calendário: os três `*_lead` em paralelo falhavam → lock.
- Tolerância "generosa" num verificador torna-o inútil: medir a taxa de aceitação com números ao acaso.
- Retomar uma execução: um nó gravado só vale se as suas dependências também foram reaproveitadas (o `dossier`
  ficava com lacunas falsas depois de um limite de utilização).
- `allowed_tools` só dá permissão; para tirar tools do contexto é `tools=`. Sem `strict_mcp_config`, os agentes
  herdam os conectores MCP da conta.
- Uma janela de tempo no texto ("em 90 dias") não é um dado: o guard não a deve conferir.
- Heredocs do bash com muito texto e aspas falham no Windows: escrever o script num ficheiro e correr.
