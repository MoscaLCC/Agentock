# Plano de implementação — Agentock

> Estado em 2026-11-14 (rev. 2). Documento vivo: atualizar o estado de cada fase à medida que avança.

## 0. Ponto de partida

**Já existe e está testado**
- Motor: agentes como pacotes (`agent.yaml` + prompt + skills + scripts + templates + MCPs), dois tipos (`llm` e `script`), loader e runner (`core/`).
- `memory_agent` + `change_alert_agent` (SQLite, histerese, Telegram) — 7 testes a passar.
- Escala de classificação fixa (`core/ratings.py`) e contrato `Synthesis` (`core/schemas.py`).
- `tools/probe_sources.py` — teste de cobertura das fontes por mercado (resultados na secção 3).

**Existe mas nunca correu**
- `news_4_hours_agent` (nunca foi executado contra a web).
- Envio real por Telegram.
- `universe_agent` — usa FMP; **a reescrever** sobre yfinance (Fase 8).

**Decisões tomadas**
| # | Decisão | Porquê |
|---|---|---|
| D1 | Trigger manual: `python flow.py <TICKER>` ou `--universe` | pedido do utilizador |
| D2 | Uma ação de cada vez por agora; modo 500 mantém-se | custo |
| D3 | Código onde os dados são estruturados; LLM só para interpretar/sintetizar | mesmos ou melhores resultados, menos custo |
| D4 | Alertas por Telegram | pedido do utilizador |
| D5 | **yfinance é a fonte principal em todos os mercados; FMP (plano grátis) é complemento só para ações dos EUA e alguns ADRs** | o plano grátis do FMP só cobre EUA, sem intraday, notícias nem screener, com 250 chamadas/dia; nos EUA traz dados que o yfinance não tem (secção 3.1) |
| D12 | **Fornecedores complementares: Finnhub, Alpha Vantage, Alpaca, Twelve Data, EODHD, Marketstack, Tiingo, iTick, GuruFocus** — cada um com papel definido (secção 3.4), atrás do router com quotas | redundância, validação cruzada de preços e dados únicos (sentimento, insiders, câmbio) |
| D6 | **A classificação anterior NÃO é passada ao `rating_agent`** | evita ancoragem e mantém cada classificação independente — condição para a avaliação da Fase 7 valer alguma coisa. A estabilidade fica a cargo da histerese do `change_alert_agent`, e o "o que mudou" é calculado por código (diff das razões) |
| D7 | **Debate bull/bear no 2.19** | o orçamento não é restrição e a qualidade é. v1 (um só LLM) fica como linha de base; v2 (debate) passa a padrão na Fase 6; as duas comparam-se na Fase 7 |
| D8 | **`asia_lead_agent` incluído** | sinal Ásia → Europa/EUA |
| D9 | **Mercados: EUA, Europa, Japão, China (Xangai, Shenzhen), Hong Kong, Coreia (KOSPI, KOSDAQ)** | pedido do utilizador |
| D10 | SEC EDGAR: User-Agent em `SEC_USER_AGENT` no `.env` (já preenchido) | exigência da SEC |
| D11 | OpenDART: sim, chave em `DART_API_KEY` no `.env` | comunicados oficiais coreanos no 2.13 |

---

## 1. Princípios

1. **Números vêm de código, não do LLM.** O LLM interpreta números que um script calculou; nunca os inventa.
2. **Contratos JSON entre agentes** (pydantic). Tudo é gravado — cada output de cada agente, por execução.
3. **Falha isolada.** Um agente que falha devolve `status: failed`; a síntese continua e sabe o que falta.
4. **Cache por âmbito.** Dados de setor/indústria calculam-se uma vez e servem todas as ações do setor.
5. **Fontes grátis são frágeis** → cache agressiva, limite de pedidos, retries, e uma fonte alternativa por dado crítico.
6. **Medir tudo:** custo, tempo e — mais tarde — se as classificações acertam.

---

## 2. Arquitetura

```
TRIGGER (ticker | --universe)
   │
   ├─ 0.1 universe_agent ............ (só no modo --universe)
   │
   └─ por ticker:
      0.2 profile_agent  ─────────────► contexto: nome, bolsa, país, moeda, setor, outras cotações, peers, mercado
         │
         ├─ CAMADA 1 — dados (scripts, paralelo)
         │     2.5a asia_lead   2.5 europe_lead   2.6 us_lead
         │     2.7 health_momentum   2.14 calendar   2.16 analysts   2.17 price_targets   2.8a indicadores
         │
         ├─ CAMADA 1b — notícias (LLM, paralelo, multilíngue)
         │     2.1 news_4h   2.2 news_24h   2.3 news_7d   2.4 news_30d
         │
         ├─ CAMADA 2 — análise (script + LLM)
         │     2.8 técnica   2.9 fundamental   2.10 sentimento
         │     2.11 quota de mercado   2.12 concorrentes   2.13 parceiras/subsidiárias
         │
         ├─ CAMADA 3 — síntese (LLM)
         │     2.15 timing   2.18 forecast   2.19 classificação (debate bull/bear) ──► Synthesis
         │
         └─ CAMADA 4 — estado
               3 memory_agent ──► 4 change_alert_agent ──► Telegram
```

A ordem de execução é declarada num `flow.yaml` (agente + `depends_on`); o orquestrador corre cada camada em paralelo.

---

## 3. Fontes de dados (grátis, sem chave)

### 3.1 Cobertura verificada — `tools/probe_sources.py`, 2026-11-14

**yfinance 1.8.0**

| Dado | EUA | Europa | Japão | HK | Xangai | Shenzhen | KOSPI | KOSDAQ |
|---|---|---|---|---|---|---|---|---|
| EOD 1 ano | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Intraday 5 min | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Market cap, bolsa, moeda | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Notícias | ✅ 10 | ✅ 10 | ✅ 10 | ✅ 10 | ⚠️ 3–10 | ✅ 10 | ✅ 10 | ✅ 5 |
| Calendário | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Preço-alvo (agregado) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Recomendações (contagens) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Upgrades/downgrades por casa | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | — |
| Demonstração de resultados, setor | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

(— = não testado nesse ticker.) Cotações cruzadas verificadas: `9988.HK` ↔ `BABA` e `601318.SS` ↔ `2318.HK` (ações A/H).

**akshare 1.20.44** — `stock_news_em("600519")` devolve notícias chinesas do Eastmoney com título, conteúdo, hora, fonte e link. A hora vem **em hora de Pequim, sem fuso** → normalizar para UTC no script.

**GDELT DOC API** — respondeu **429 (Too Many Requests) logo ao primeiro pedido**. Fica como fonte secundária, com backoff; não é fiável como primária.

**FMP, plano grátis** — `tools/probe_fmp.py`, 2026-11-14 (250 chamadas/dia, 512 MB/30 dias)

| Endpoint | AAPL | ADRs (BABA, TSM) | ASML (ADR) | Fora dos EUA (.AS .T .HK .SS .KS) |
|---|---|---|---|---|
| profile, quote, EOD | ✅ | — | — | ❌ 402 |
| intraday 5 min | ❌ 402 | — | — | ❌ |
| notícias por ticker | ❌ 402 | — | — | ❌ 402 |
| screener | ❌ 402 | | | |
| peers | ✅ 10 | ✅ BABA | — | — |
| grades (histórico por casa, 1820 linhas), grades-consensus | ✅ | — | ❌ 402 | ❌ 402 |
| price-target consensus/summary, ratings-snapshot | ✅ | ✅ TSM | — | ❌ 402 |
| analyst-estimates | ✅ | — | — | — |
| financial-scores (Piotroski/Altman) | ✅ | ✅ BABA | — | ❌ 402 |
| key-metrics-ttm, ratios-ttm, income | ✅ | — | — | ❌ 402 |
| revenue-product-segmentation | ✅ 17 | — | — | — |
| DCF | ✅ | — | — | — |
| earnings (histórico com surpresas) | ✅ 166 | — | — | — |
| all-exchange-market-hours | ✅ 81 bolsas: estado atual + fuso (testado ao sábado: tudo "CLOSED"; horários das sessões a confirmar num dia útil) | | | |

Conclusão: a cobertura é por símbolo e não está garantida, mesmo em ADRs. O router de dados (Fase 1) tenta o FMP para ações dos EUA, memoriza os 402 por símbolo/endpoint para não gastar chamadas, e cai para o yfinance.

### 3.2 Limitações conhecidas

| Limitação | Impacto | Mitigação |
|---|---|---|
| yfinance é não-oficial; relatos de 429 e de quebras quando o Yahoo muda o site | todos | cache SQLite com TTL, limite de pedidos, retries, `yf.download` em lote, alternativa por mercado (akshare para China/HK) |
| Screener do yfinance mistura moedas e inclui listagens estrangeiras (ex.: `AAPLCO.CL`, `BABA.BA` no topo) | 0.1 top 500 | screener por região → converter para USD → excluir CDR/listagens secundárias → deduplicar por empresa → validar contra uma lista de referência |
| Sem upgrades/downgrades por casa fora dos EUA | 2.16, 2.17 | EUA: FMP grades + yfinance; resto: web (LLM); akshare para ratings de casas chinesas (a verificar) |
| Sem segmentação de receitas fora dos EUA | 2.11 | EUA: FMP; resto: LLM + web + receitas dos peers |
| Sem lista de peers fora dos EUA | 2.12 | EUA/ADRs: FMP peers; resto: LLM propõe → screener do yfinance valida |
| Sem horários das sessões via API | 2.5, 2.6 | `config/markets.yaml` (sessões, pausa de almoço) + fusos do FMP + `exchange_calendars` para feriados (a verificar) |
| Sem scores (Piotroski, Altman) nem DCF fora dos EUA | 2.7, 2.9 | EUA: FMP; resto: script próprio com pressupostos explícitos (validado contra o FMP nas ações dos EUA) |
| FMP: 250 chamadas/dia | todos os que usam FMP | cache com TTL, contador diário no SQLite, fallback para yfinance ao esgotar |

### 3.3 Repositórios a reutilizar

| Repo | Uso | Estado |
|---|---|---|
| [yfinance](https://github.com/ranaroussi/yfinance) | fonte principal, todos os mercados | ✅ verificado |
| [akshare](https://github.com/akfamily/akshare) | China/HK: notícias em chinês, dados A-share | ✅ notícias verificadas; o resto a verificar |
| [pandas-ta-classic](https://pypi.org/project/pandas-ta-classic/) | indicadores técnicos (fork mantido; o `pandas-ta` original anuncia arquivo) | a verificar |
| [dart-fss](https://pypi.org/project/dart-fss/) / [opendart-fss-mcp](https://glama.ai/mcp/servers/hypn4/opendart-fss-mcp) | Coreia: comunicados oficiais (DART). Chave grátis OpenDART | a verificar; opcional |
| [pykrx](https://github.com/sharebook-kr/pykrx) / [FinanceDataReader](https://github.com/FinanceData/FinanceDataReader) | Coreia: fluxos de investidores estrangeiros/institucionais (sinal forte neste mercado) | a verificar; opcional |
| GDELT DOC API | notícias globais em 65 línguas | ⚠️ 429; secundária |
| SEC EDGAR | EUA: filings (2.13) | a verificar; exige User-Agent com contacto |
| [OpenBB](https://pypi.org/project/OpenBB/) | agregador de fontes | **não adotado**: licença AGPL e os bons fornecedores pedem chave |
| [TradingAgents](https://github.com/TauricResearch/TradingAgents) | inspiração para o debate bull/bear (2.19) | só desenho, não código (usa LangGraph) |
| FMP (plano grátis) | complemento para EUA e alguns ADRs | ✅ verificado (secção 3.1) |

### 3.4 Fornecedores complementares

Cobertura **verificada** com `tools/probe_providers.py` em 2026-11-14 (sábado). Limites: comparativos de 2026 / páginas oficiais, salvo indicação. Todos os planos grátis são para **uso pessoal/não comercial**.

| Fornecedor | Plano grátis | EUA | Europa | HK | China A | Japão | Coreia | Papel no Agentock |
|---|---|---|---|---|---|---|---|---|
| **yfinance** | sem chave; 429 ocasionais | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **principal** em tudo |
| **FMP** | 250/dia | ✅ rico | ❌ | ❌ | ❌ | ❌ | ❌ | fundamentais, analistas por casa, peers, segmentos, DCF (EUA + alguns ADRs) |
| **iTick** | limite por minuto apertado (429 após ~6 pedidos seguidos) | — | — | ✅ cotação + intraday 5 min | ✅ SH, SZ | ✅ | ✅ | **2.ª fonte de cotações e intraday na Ásia** — dados reais verificados (preço, OHLC, volume, variação). Chamadas espaçadas |
| **EODHD** | ~20/dia | ✅ | ✅ | ✅ | ✅ | — | ✅ | **validação cruzada de preços fora dos EUA**; notícias ✅ |
| **Tiingo** | 1000/dia, 50/hora | ✅ EOD + IEX 5 min | — | — | ✅ EOD | — | — | **2.ª fonte EOD para China A**; intraday EUA. Notícias: ❌ 403 (pago) |
| **Finnhub** | 60/min | ✅ notícias (248/semana), recomendações, sentimento de insiders | — | ❌ 403 | — | — | ❌ 403 | **notícias por ticker e insiders (EUA)** |
| **Alpaca** | 200/min, IEX | ✅ cotação, intraday 5 min, **notícias** | — | — | — | — | — | **tempo real e intraday EUA**; notícias EUA |
| **Twelve Data** | 800/dia, 8/min | ✅ cotação, intraday | — | ❌ (plano Pro) | — | — | ❌ (plano Pro) | **câmbios** (normalização USD do top 500) ✅ |
| **Alpha Vantage** | 25/dia, ~1 pedido/s | ✅ cotação | — | — | ✅ EOD `.SHH` | — | — | **baixo valor**: `NEWS_SENTIMENT` passou a pago; fica como último recurso de EOD |
| **Marketstack** | 100/mês ou /dia | ✅ EOD | — | — | — | — | ❌ formato de símbolo | **último recurso** EOD (EUA) |
| **GuruFocus** | ~100/mês grátis; ~200/mês com Premium (terceiros) | sem chave ainda | | | | | | **dados de análise únicos**: GF Value, ranks de solidez/rentabilidade, superinvestidores (13F), insiders. 1–2 chamadas por ação, cache 7–30 dias → 2.9, 2.10, 2.16. **Integração via MCP oficial** (`https://api.gurufocus.com/mcp`, header `Authorization`; mesmo token da Data API, que exige Premium segundo o tutorial oficial) |

(— = não testado.) Existe um [servidor MCP comunitário do iTick](https://glama.ai/mcp/servers/@hmq19900504/itick-mcp/blob/4e59e66ccbecb5c6a8a59d952780c2841a7b7124/MARKET_SUPPORT.md) (não verificado); a decisão é usar o nosso cliente, para controlar quotas no router.

**Cobertura por mercado depois disto — quantas fontes independentes de preço:**
EUA 8 · Europa 2 (yfinance, EODHD) · HK 3 (yfinance, iTick, EODHD) · China A 5 (yfinance, iTick, EODHD, Tiingo, akshare) · Japão 2 (yfinance, iTick) · Coreia 3 (yfinance, iTick, EODHD).
**Notícias:** EUA 4 fontes + web; China akshare + web; resto yfinance + EODHD + web.

**O que o router faz com isto (Fase 1)**
- **Prioridade por dado e por mercado**, ex.: intraday EUA → Alpaca → Tiingo → yfinance; intraday Ásia → yfinance → iTick; notícias EUA → Finnhub + Alpaca + yfinance + web; EOD China → yfinance → Tiingo → EODHD; câmbios → Twelve Data → yfinance.
- **Livro de quotas** no SQLite (por minuto, dia e mês, por fornecedor): nunca ultrapassa; ao esgotar, passa ao seguinte.
- **Validação cruzada:** o último fecho vem de 2 fontes; divergência > 1% marca o dado como suspeito na saída do agente.
- **Notícias agregadas:** yfinance + Finnhub + Alpaca + EODHD + akshare + web → deduplicação → agentes 2.1–2.4.
- **MCP oficial vs cliente próprio:** dados numéricos em volume (preços, intraday, câmbios) → cliente próprio atrás do router. Dados de análise, pouco volume, consumidos pelo LLM (GuruFocus) → MCP oficial no `agent.yaml`, **só nos agentes que precisam**, com hook `PreToolUse` que conta cada chamada no livro de quotas e bloqueia ao esgotar.

---

## 4. Mercados

| Mercado | Sufixo | Sessão (hora local) | Fuso | Particularidades |
|---|---|---|---|---|
| EUA (NYSE, Nasdaq) | — | 09:30–16:00 | America/New_York | pré e pós-mercado; futuros quase 24 h |
| Europa (Xetra, Euronext, LSE, SIX…) | .DE .AS .PA .L .SW … | ~09:00–17:30 | Europe/* | — |
| Japão (TSE) | .T | 09:00–11:30, 12:30–15:30 | Asia/Tokyo | pausa de almoço |
| Coreia (KOSPI / KOSDAQ) | .KS / .KQ | 09:00–15:30 | Asia/Seoul | limite diário ±30%; fluxos de estrangeiros relevantes |
| China (Xangai / Shenzhen) | .SS / .SZ | 09:30–11:30, 13:00–15:00 | Asia/Shanghai | limite diário ±10% (±20% STAR/ChiNext); ações A/H |
| Hong Kong | .HK | 09:30–12:00, 13:00–16:00 | Asia/Hong_Kong | muitas cotações duplas com EUA e China |

Horários e fusos vão para `config/markets.yaml` e são calculados com `zoneinfo` — as horas de verão mudam a sobreposição entre sessões ao longo do ano. **Confirmar estes horários na Fase 0** antes de os fixar.

**O ciclo de 24 h que os agentes 2.5/2.6 exploram:**
```
Ásia fecha ──► Europa abre ──► EUA abrem (Europa ainda aberta) ──► EUA fecham ──► Ásia abre ──► …
   asia_lead         europe_lead                                     us_lead
 (p/ Europa e EUA)  (p/ EUA)                                      (p/ Ásia e Europa)
```
Com a China e a Coreia, o `us_lead_agent` deixa de servir só a Europa: o fecho americano é a informação mais recente antes de a Ásia abrir.

**Impacto nos agentes**
- **Notícias (2.1–2.4):** pesquisas em chinês, coreano e japonês, além de inglês; `references/sources_by_market.md` na skill; akshare para notícias chinesas.
- **Técnica e timing (2.8, 2.15):** ter em conta limites diários de variação (China, Coreia) e pausas de almoço.
- **Sentimento (2.10):** fluxos de investidores estrangeiros na Coreia (opcional, pykrx).
- **Relações (2.13):** DART (Coreia), CNINFO/akshare (China), HKEXnews (HK), SEC (EUA).
- **Feriados:** Ano Novo Lunar, Golden Week, Chuseok → `exchange_calendars`.

---

## 5. Catálogo de agentes

Legenda — **Tipo:** S = script (sem LLM), L = LLM, S+L = script calcula e LLM interpreta.
**Artefactos:** sk = skill, sc = script, tp = template, hk = hook, sub = subagentes, ref = referências, cfg = configuração.

| # | Agente | Tipo | Fontes principais | Artefactos | Cache | Depende de |
|---|---|---|---|---|---|---|
| 0.1 | `universe_agent` | S | screener yf por região + FX | sc normalização USD/dedupe | 1 dia | — |
| 0.2 | `profile_agent` **(novo)** | S | yf info/fast_info, yf Search (a verificar) | ref cross_listings.yaml, cfg markets.yaml | 7 dias | — |
| 2.1 | `news_4_hours_agent` | L | WebSearch/WebFetch, yf news, akshare (China), GDELT | sk news-triage, sc check_window + dedupe, ref sources_by_market, tp | sempre fresco | 0.2 |
| 2.2 | `news_24_hours_agent` | L | idem (herda `news_base`) | idem | 1 h | 0.2 |
| 2.3 | `news_7_days_agent` | L | idem | idem | 6 h | 0.2 |
| 2.4 | `news_30_days_agent` | L | idem | idem | 24 h | 0.2 |
| 2.5a | `asia_lead_agent` **(novo)** | S | yf intraday: própria ação noutra bolsa, peers asiáticos, ^N225 ^KS11 ^HSI 000001.SS | sc session_map, cfg markets.yaml, ref proxies.yaml | 15 min | 0.2 |
| 2.5 | `europe_lead_agent` | S | yf intraday: cotação europeia, peers europeus, ^STOXX50E ^GDAXI | idem | 15 min | 0.2 |
| 2.6 | `us_lead_agent` | S | yf: fecho e after-hours dos EUA, ADR, ^GSPC ^IXIC, futuros ES=F NQ=F (a verificar) | idem | 15 min | 0.2 |
| 2.7 | `health_momentum_agent` | S | yf demonstrações + info + EOD + índice local | sc scores (Piotroski, Altman, momentum) | 1 dia | 0.2 |
| 2.8 | `technical_agent` | S+L | yf EOD + intraday | sc indicators (pandas-ta-classic), sk technical-reading | 1 dia | 0.2 |
| 2.9 | `fundamental_agent` | S+L | yf demonstrações, info | sc valuation (DCF próprio, múltiplos vs peers), sk fundamental-framework | 1 dia | 0.2, 2.12 |
| 2.10 | `sentiment_agent` | L | 2.1–2.4, 2.16, fluxos Coreia (opcional) | sk sentiment-rubric | por execução | 2.1–2.4, 2.16 |
| 2.11 | `market_share_agent` | S+L | web + receitas dos peers (yf) | sk, ref | 30 dias, por indústria | 0.2, 2.12 |
| 2.12 | `competitors_agent` | S+L | LLM propõe peers → screener yf valida → script compara | sc comps, sub peer_validator | 1 dia, por indústria | 0.2 |
| 2.13 | `relations_agent` | L | SEC, DART, CNINFO/akshare, web | sk, ref filings_by_market | 30 dias | 0.2 |
| 2.14 | `calendar_agent` | S | yf calendar, earnings dates | — | 1 dia | 0.2 |
| 2.15 | `timing_agent` | L | 2.5a, 2.5, 2.6, 2.8, 2.10, 2.14 | sk timing-rules (incl. limites diários) | por execução | camada 2 |
| 2.16 | `analysts_agent` | S (+L fora dos EUA) | yf recommendations; upgrades_downgrades (EUA); web | — | 1 dia | 0.2 |
| 2.17 | `price_targets_agent` | S (+L fora dos EUA) | yf analyst_price_targets (atual/mín/máx/média/mediana); alvos por casa (EUA); web | — | 1 dia | 0.2 |
| 2.18 | `forecast_agent` | S+L | volatilidade (script), 2.8, 2.9, 2.17 | sc ranges, sk scenarios | por execução | camada 2 |
| 2.19 | `rating_agent` | L | tudo | sub bull + bear + juiz, sk rating-rubric, hk anti-alucinação | por execução | 2.15, 2.18 |
| 3 | `memory_agent` ✅ | S | SQLite | — | — | 2.19 |
| 4 | `change_alert_agent` ✅ | S | SQLite, Telegram | sc diff de razões | — | 3 |
| — | `eval_agent` **(novo)** | S | histórico + EOD | tp relatório | — | 3 |

**Ações dos EUA (e ADRs cobertos):** o router de dados usa primeiro o FMP em 0.2 (peers), 2.7 (financial-scores), 2.9 (métricas, rácios, DCF, estimativas), 2.11 (segmentação de receitas), 2.12 (peers), 2.14 (histórico de resultados com surpresas), 2.16 (grades por casa) e 2.17 (price-target summary). Nos restantes mercados, e se o FMP falhar, usa as fontes da tabela.

### Notas por agente

- **0.2 profile_agent (novo):** quase todos os agentes precisam de saber a bolsa, o mercado, a moeda, o setor e as outras cotações (ADR, A/H, GDR). Resolve-se uma vez e passa a ser o contexto do resto. Para as outras cotações: tabela manual dos pares conhecidos (`cross_listings.yaml`) + pesquisa do yfinance.
- **2.1–2.4 notícias:** um pacote base `agents/_shared/news_base/` (prompt, skill, scripts, schema). Os quatro agentes são `agent.yaml` finos com `extends: news_base` e a sua janela/TTL. Mantêm-se separados porque cada janela tem estratégia diferente: 4 h = notícias de última hora, sempre fresco; 30 dias = só os acontecimentos marcantes, em cache 24 h.
- **2.5a / 2.5 / 2.6 sinais entre sessões:** um motor genérico (`session_map`) usa `markets.yaml` para saber, no momento do trigger, que bolsas estão abertas ou fechadas em relação à bolsa principal da ação. Sinais por ordem de força: (1) a própria ação noutra bolsa, (2) futuros do índice, (3) peers do setor na sessão que lidera, (4) índice dessa sessão. Saída: variação desde o fecho da bolsa principal, por proxy, com peso e confiança. Sem proxy relevante → `applicable: false`, sem ruído.
- **2.8 técnica:** o script calcula SMA 50/200, EMA, RSI, MACD, ATR, Bollinger, volume relativo, suportes e resistências (pivots), e marca proximidade aos limites diários (China, Coreia). O LLM só lê o JSON.
- **2.12 concorrentes:** sem lista de peers na fonte, o LLM propõe e um subagente valida com o screener (mesma indústria, dimensão comparável) antes de o script montar a tabela de comparáveis.
- **2.18 forecast:** cenários e não preço pontual — bear/base/bull com intervalos a 1, 3 e 12 meses. O intervalo estatístico vem de script (volatilidade histórica); a ancoragem vem dos preços-alvo e do DCF.
- **2.19 classificação:** v1 = um só LLM com rubrica (linha de base). v2 = subagente bull + subagente bear + juiz. Um hook valida que os números citados nas razões existem nos inputs.
- **4 change_alert_agent:** a mensagem de Telegram passa a incluir o que mudou nas razões face à classificação anterior (diff por código, ver D6).

---

## 6. Fases

Ordem pensada para ter **uma ação a dar classificação de ponta a ponta o mais cedo possível** (Fase 2) e depois alargar.

### Fase 0 — Verificações e fundações
| Tarefa | Aceitação |
|---|---|
| ~~Cobertura de fontes por mercado~~ | ✅ feito (secção 3.1) |
| ~~Cobertura do plano FMP~~ | ✅ feito (secção 3.1) |
| ~~Chaves dos fornecedores complementares + `probe_providers.py`~~ | ✅ feito (secção 3.4); falta só GuruFocus |
| Repetir `all-exchange-market-hours` num dia útil | saber se devolve horários das sessões ou só estado |
| Verificar o resto: futuros (`ES=F`, `NQ=F`), `yf.Search`, campos de alvo em `upgrades_downgrades`, `exchange_calendars` (XSHG, XSHE, XHKG, XKRX, XTKS), GDELT com backoff, akshare para dados A-share além das notícias | `docs/coverage.md` atualizado |
| Confirmar horários das bolsas e preencher `config/markets.yaml` | sobreposições de sessão corretas em inverno e verão |
| `git init` + primeiro commit | repositório com `.gitignore` (já existe) |
| ~~Carregar `.env` (`python-dotenv`)~~ | ✅ `core/env.py` |
| Bot Telegram (@BotFather) + `tools/telegram_setup.py` (script feito) | mensagem recebida no telemóvel |
| Primeira execução real do `news_4_hours_agent` (AAPL e 005930.KS) | JSON válido; skill carregada; `check_window` executado em Windows; custo registado |

### Fase 1 — Motor
| Tarefa | Aceitação |
|---|---|
| `core/data/`: cliente de dados por fonte (yfinance, akshare, FMP) com retries, limite de pedidos, cache SQLite com TTL, normalização de símbolos e de fusos | testes com respostas gravadas (fixtures) |
| `core/data/providers/<nome>.py`: um módulo por fornecedor que declara capacidades (dado × mercado) e quotas | adicionar um fornecedor não mexe nos agentes |
| `core/data/router.py`: prioridade por dado e mercado (secção 3.4); livro de quotas no SQLite (minuto/dia/mês); memória de 402/403 por símbolo/endpoint; validação cruzada de preços | uma ação europeia nunca gasta quota de fornecedores só-EUA; ao esgotar um fornecedor passa ao seguinte; divergência de preço > 1% é sinalizada |
| Servidor MCP in-process `market` (`create_sdk_mcp_server`): expõe o cliente aos agentes LLM; os agentes script chamam o mesmo cliente diretamente | um agente LLM chama `mcp__market__quote` |
| `agent.yaml` alargado: `extends`, `model`, `effort`, `max_budget_usd`, `cache_ttl`, `cache_scope` (ticker / indústria / global), `hooks`, `subagents` | testes do loader |
| Cache de outputs no runner (agente + âmbito + hash dos inputs) | segunda execução dentro do TTL não chama o LLM |
| `core/hooks.py`: registo de cada tool call (`PostToolUse`) em `data/logs/<run_id>.jsonl`; bloqueio de domínios (`PreToolUse`) | log gerado; domínio bloqueado é recusado |
| Orquestrador DAG a partir de `flow.yaml`: camadas em paralelo, timeout por agente, `AgentResult(status, output, error, cost, duration)` | `python flow.py AAPL --dry-run` mostra o DAG |
| Tabela `agent_outputs` (run_id, agente, ticker, JSON, custo, duração) | cada execução fica reconstituível |
| CLI: `--only <agente>`, `--no-cache`, `--dry-run` | — |

### Fase 2 — Fatia vertical (marco M1)
Agentes: 0.2 profile, 2.1 news_4h, 2.8 técnica, 2.14 calendário, 2.16 analistas, 2.17 preços-alvo, 2.19 classificação v1 → memória → alerta.

**Aceitação M1:** `python flow.py AAPL` e `python flow.py 005930.KS` produzem uma classificação gravada; uma segunda execução com mudança dispara Telegram; custo e tempo por agente visíveis.

### Fase 3 — Dados restantes
2.5a asia_lead, 2.5 europe_lead, 2.6 us_lead, 2.7 health_momentum, 2.9 fundamental.
**Aceitação:** testes com fixtures; corre para um ticker de cada mercado da secção 4; `applicable: false` quando não há proxy; pares A/H e ADR detetados.

### Fase 4 — Notícias completas e sentimento
Refatorar para `news_base`; 2.2, 2.3, 2.4; pesquisa multilíngue; script de deduplicação; 2.10 sentimento.
**Aceitação:** a mesma notícia não aparece duplicada entre fontes; cada janela respeita o seu TTL; notícias chinesas e coreanas aparecem para ações desses mercados.

### Fase 5 — Análise competitiva
2.11 quota de mercado, 2.12 concorrentes, 2.13 parceiras/subsidiárias, com cache por indústria.
**Aceitação:** duas ações da mesma indústria reutilizam a mesma análise de setor.

### Fase 6 — Síntese completa
2.15 timing, 2.18 forecast, 2.19 v2 (debate bull/bear + juiz), hook anti-alucinação, guardrail "análise, não aconselhamento personalizado", diff de razões no alerta.
**Aceitação:** as razões citam só números presentes nos inputs; a classificação inclui confiança e o que falhou a montante.

### Fase 7 — Avaliação
`python flow.py --backfill` preenche retornos a 1, 7 e 30 dias; `eval_agent` gera relatório de acerto por classificação, por nível de confiança, por mercado e por versão (v1 vs v2), contra o índice local.
**Aceitação:** relatório com N ≥ 30 classificações avaliadas. Sem isto não se sabe se o sistema vale mais que o acaso.

### Fase 8 — Universo e escala
Reescrever o `universe_agent` sobre o screener do yfinance (por região, conversão para USD, exclusão de listagens secundárias, deduplicação, validação contra lista de referência); concorrência limitada (semáforo); retomar depois de falha; **estimativa de custo antes de correr** (custo medido por ação × N, exige `--yes`).
**Aceitação:** `--universe --top 20` completa; o top 20 bate com uma lista pública de referência; a estimativa fica a menos de 30% do real.

### Fase 9 — Opcional
- **Bot Telegram como trigger:** `/run AAPL`, `/status AAPL`, `/history AAPL` — disparar a partir do telemóvel.
- **Página de histórico:** gráfico de classificação vs preço por ação.

---

## 7. Transversal

- **Modelos por agente** (no `agent.yaml`): Haiku 5.5 para triagem e extração, Sonnet 5.5 para análise, Opus 5.5 para a síntese (2.15, 2.18, 2.19). `max_budget_usd` por agente como travão.
- **Testes:** funções puras (unitários); agentes script com fixtures gravadas; contratos (schemas); agentes LLM com smoke tests (JSON válido, campos preenchidos), não respostas exatas; avaliação real na Fase 7.
- **Observabilidade:** log JSONL por execução, custo e duração por agente, tabela `agent_outputs`.
- **Fusos:** tudo gravado em UTC; conversão na entrada (akshare vem em hora de Pequim sem fuso).
- **Segredos:** só em `.env` (ignorado pelo git).
- **Guardrails:** o sistema produz análise; a saída leva sempre confiança, razões e lacunas de dados.

---

## 8. Riscos

| Risco | Mitigação |
|---|---|
| yfinance bloqueado (429) ou partido por mudança no Yahoo | cache, limite de pedidos, versão fixada, akshare como alternativa na China/HK, isolamento atrás de `core/data/` para trocar de fonte sem mexer nos agentes |
| Notícias chinesas/coreanas fracas no Yahoo | akshare (China), pesquisa web na língua local |
| Notícias inventadas ou fora da janela | `check_window` + WebFetch obrigatório + URL no output |
| Peers errados contaminam 2.11 e 2.12 | subagente de validação |
| Sinais entre sessões fracos para a maioria das ações | `applicable: false` + medir na Fase 7 |
| Top 500 errado por moedas/listagens duplicadas | normalização USD + validação contra lista de referência |
| Custo com 500 ações | cache por âmbito, scripts em vez de LLM, estimativa antes de correr |
| Classificação oscilante | histerese já implementada (D6) |
| Tool Bash do SDK em Windows | validar na Fase 0 (execução real) |

---

## 9. Decisões em aberto

Nenhuma de momento. Pendências do utilizador: criar o bot Telegram (`python tools/telegram_setup.py`) e registar a chave OpenDART.
