# Plano de implementação — Agentock

> Estado em 2026-11-14 (rev. 5 — **todas as fases implementadas**; ver "Pendências"). Documento vivo.

## 0. Estado

| Fase | Estado | Evidência |
|---|---|---|
| 0 — Verificações e fundações | ✅ | cobertura de 13 fontes testada; Telegram; git |
| 1 — Motor | ✅ | router de dados (13 fornecedores), orquestrador DAG, cache, hooks, tools `market` |
| 2 — Fatia vertical (M1) | ✅ | AAPL (v1) e 005930.KS (v2, debate) classificadas e gravadas; alerta real no Telegram (`tools/test_alert.py`) |
| 3 — Dados restantes | ✅ | 9988.HK: sinais entre sessões aplicáveis (BABA + futuros após o fecho de HK), Piotroski/Altman, DCF com conversão CNY→HKD |
| 4 — Notícias e sentimento | ✅ | 4 janelas (4h/24h/7d/30d) + sentimento correram para AAPL |
| 5 — Análise competitiva | ✅ | AAPL: peers validados (GoerTek rejeitada como fornecedora), comps, quotas IDC, 19 subsidiárias do Exhibit 21 |
| 6 — Síntese completa | ✅ código / ⚠️ 1 validação | timing e forecast correram; a classificação com o dossier completo falhou por **falta de créditos da API** (ver Pendências) |
| 6b — IPOs | ✅ código / ⚠️ validação | calendário real (Anthropic, 19-nov, 74 mil M USD; 2 SPACs excluídos); `pre_ipo_agent` e `ipo_web_agent` ainda não correram (créditos) |
| 7 — Avaliação | ✅ código | backfill + relatório; precisa de tempo: N ≥ 30 classificações com 30 dias |
| 8 — Universo e escala | ✅ | top 500 em ~8 s, 18/18 megacaps de referência, estimativa de custo antes de correr |
| 9 — Bot Telegram + histórico | ✅ código | `tools/telegram_bot.py` (só o teu chat); página HTML de histórico gerada |

**62 testes unitários** (`python -m unittest discover -s tests -t .`) + testes reais (`tools/smoke_data.py`, `tools/probe_*.py`).

### Pendências
1. **Créditos da API Anthropic esgotados** (erro "Credit balance is too low" a meio da execução completa da AAPL). Opções: carregar créditos, ou retirar `ANTHROPIC_API_KEY` do `.env` para o SDK usar o login do Claude Code. **Decisão do utilizador** (afeta faturação).
2. Depois dos créditos: correr `python flow.py AAPL` (classificação v2 com o dossier completo), `python flow.py --ipos` (análise do IPO da Anthropic + `ipo_web_agent`).
3. GuruFocus: o token não tem acesso à API ("API is for data users only"); fica desligado por `requires_env`/sem uso.
4. Fase 7: o relatório só é fiável com N ≥ 30 classificações avaliadas a 30 dias — correr `--backfill` e `--eval` periodicamente.

---

## Como usar

```
python flow.py AAPL                     # análise completa (aceita nome "Samsung" ou código "005930")
python flow.py AAPL --rating v1         # classificação sem debate (mais barata; v2 é o padrão)
python flow.py AAPL --verbose           # output de todos os nós
python flow.py AAPL --only fundamental_data   # um nó
python flow.py AAPL --dry-run           # DAG
python flow.py --ipos                   # calendário de IPOs + análise de cada um (máx. 5)
python flow.py --ipos --set analyze=false
python flow.py --ipo "Nome da empresa"
python flow.py --universe --top 50      # universo + estimativa de custo; --yes para correr; --parallel N; --resume
python flow.py --backfill && python flow.py --eval
python flow.py --report AAPL            # data/reports/AAPL_historico.html
python tools/telegram_bot.py            # bot: /run AAPL, /status AAPL, /history AAPL, /ipos
```
Custo observado: ~1,4 USD por ação no fluxo completo sem a classificação; a classificação v2 custou 0,18 USD na Samsung (dossier mais pequeno). A estimativa do `--universe` usa a média das execuções completas gravadas.

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

---

## 1. Princípios
1. Números vêm de código; o LLM interpreta e cita — o guard verifica cada número citado.
2. Contratos JSON (pydantic) entre agentes; tudo gravado (`agent_outputs`).
3. Falha isolada: nós dependentes de um nó falhado ficam `skipped`; inputs opcionais seguem como `null` (lacuna).
4. Cache por âmbito (`cache_key` com caminhos, ex.: `profile.symbol`, `profile.industry`).
5. Fontes grátis são frágeis → cache, quotas, retries, fonte alternativa por dado.
6. Medir tudo: custo, tempo, acerto.

---

## 2. Arquitetura (fluxo `ticker`, 10 camadas — `python flow.py AAPL --dry-run`)

```
1  profile
2  analysts · asia/europe/us_lead · competitors · health · indicators · ipo_lifecycle · price_targets · relations
   · news_4h · news_24h · news_7d · news_30d
3  calendar · comps · market_share · sentiment · technical
4  fundamental_data · timing
5  forecast_stats · fundamental
6  forecast
7  rating (v2: juiz + subagentes bull/bear)
8  guard (verifica números, lacunas, monta a Synthesis)
9  memory
10 alert (Telegram, com diff das razões)
```
Fluxos `ipos` (ipo_web → ipo_calendar) e `ipo` (pre_ipo → ipo_memory).

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
| SEC EDGAR | EUA/ADRs: filings, Exhibit 21/8, pesquisa de prospetos, lock-up do 424B4 | documentos oficiais |
| OpenDART | Coreia: comunicados | documentos oficiais |

Capacidades: quote, eod, intraday, profile, news (merge), analyst_recs, price_targets, upgrades, peers, calendar, search, fx,
ipo_calendar (merge), financials, scores, dcf, insider, filings, subsidiaries, sec_search, lockup.
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

## 5. Catálogo de agentes (35)

S = script · L = LLM (modelo) · artefactos: sk skill, sc script, sub subagentes, tp template, mcp tools do router

| # | Agente | Tipo | Artefactos | Cache |
|---|---|---|---|---|
| 0.1 | universe_agent | S | config/universe.yaml | 1 dia |
| 0.2 | profile_agent | S | — | (router) |
| 2.1–2.4 | news_4h/24h/7d/30d (base `_shared/news_base`) | L sonnet | sk news-triage + ref fontes por mercado, sc check_window + dedupe, tp, mcp news/profile | 0 / 1h / 6h / 24h |
| 2.5a/2.5/2.6 | asia/europe/us_lead (base `_shared/lead_base`) | S | core/sessions.py | 15 min |
| 2.7 | health_momentum_agent | S | — | 12 h |
| 2.8a / 2.8 | technical_indicators_agent / technical_agent | S / L haiku | sk technical-reading | 1 h |
| 2.9a / 2.9 | fundamental_data_agent / fundamental_agent | S / L sonnet | sk fundamental-framework | 12 h |
| 2.10 | sentiment_agent | L sonnet | sk sentiment-rubric, mcp insider | — |
| 2.11 | market_share_agent | L sonnet | sk market-structure | 30 dias, **por indústria** |
| 2.12a / 2.12b | competitors_agent / comps_agent | L sonnet / S | sk peer-selection, mcp peers/search/profile | 7 dias / 1 dia |
| 2.13 | relations_agent | L sonnet | sk relations-sources, mcp subsidiaries/filings | 30 dias |
| 2.14 | calendar_agent | S | — | 6 h |
| 2.15 | timing_agent | L opus | sk timing-rules | — |
| 2.16 / 2.17 | analysts_agent / price_targets_agent | S | — | 6 h |
| 2.18a / 2.18 | forecast_stats_agent / forecast_agent | S / L opus | sk scenarios | — |
| 2.19 | rating_agent (v2) / rating_v1_agent | L opus | sk rating-rubric, sub bull/bear (sonnet), file_inputs | — |
| — | guard_agent | S | verificação de números PT/EN + unidades | — |
| 3 / 4 | memory_agent / change_alert_agent | S | diff de razões | — |
| I.1 | ipo_web_agent + ipo_calendar_agent | L sonnet + S | — | 12 h |
| I.2 | pre_ipo_agent | L opus | sk pre-ipo-analysis, sc deal_math, sub bull/bear, mcp sec_search… | 1 dia |
| I.3 | ipo_lifecycle_agent | S | lock-up do 424B4 (SEC) | 12 h |
| — | ipo_memory_agent / eval_agent | S | tp report.md | — |

---

## 6. Transversal
- Modelos: Haiku 5.5 (leitura técnica), Sonnet 5.5 (notícias, análise, subagentes), Opus 5.5 (timing, forecast, classificação, pré-IPO). `max_budget_usd` por agente.
- Observabilidade: `data/logs/<run_id>.jsonl` (cada tool call), `agent_outputs` (custo, duração, turnos), `data/runs/<run_id>/` (inputs em ficheiro).
- Segurança: `.env` fora do git; bot só responde ao chat configurado; `block_domains`.
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
