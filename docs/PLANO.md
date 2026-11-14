# Plano de implementação — Agentock

> Estado em 2026-11-14 (rev. 4 — Fases 0 e 1 concluídas). Documento vivo: atualizar o estado de cada fase à medida que avança.

## 0. Ponto de partida

**Já existe e está testado**
- Motor: agentes como pacotes (`agent.yaml` + prompt + skills + scripts + templates + MCPs), dois tipos (`llm` e `script`), loader e runner (`core/`).
- `memory_agent` + `change_alert_agent` (SQLite, histerese, Telegram) — 7 testes a passar.
- Escala de classificação fixa (`core/ratings.py`) e contrato `Synthesis` (`core/schemas.py`).
- `tools/probe_sources.py`, `probe_fmp.py`, `probe_providers.py` — cobertura das fontes por mercado (secção 3).
- Telegram: `@agentock_bot` configurado, mensagem de teste recebida.
- Repositório git (`main`).

- Motor da Fase 1: router de dados com 11 fornecedores, orquestrador DAG, cache, hooks, tools `market` — 29 testes.
- `news_4_hours_agent` executado com sucesso (APIs + web).

**Existe mas nunca correu**
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
| D13 | **IPOs: módulo próprio** — calendário, análise pré-IPO com classificação própria (Subscrever / Neutro / Evitar + confiança) e ciclo pós-IPO (estreia, fim do período de silêncio, lock-up, 1 ano) a alimentar os agentes normais | pedido do utilizador; uma empresa pré-IPO não tem cotação nem histórico, por isso não cabe no fluxo por ticker |
| D14 | **Horários e feriados das bolsas vêm do `exchange_calendars`**, não de um `markets.yaml` manual | verificado: sessões em UTC com pausas de almoço e horário de verão, em todas as bolsas cobertas |
| D15 | **akshare só como fonte secundária**, com backoff longo | o Eastmoney limitou o IP após poucos pedidos (o próprio aviso diz 5 min, até 40+ se repetido) |

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

**Fluxo de IPOs** (trigger próprio: `python flow.py --ipos [--days 30]` ou `--ipo "Nome"`):
```
I.1 ipo_calendar_agent ──► IPOs dos próximos N dias, nos mercados cobertos, acima do limiar de dimensão
   └─ por IPO: I.2 pre_ipo_agent (prospeto, estrutura da oferta, financeiras, peers cotados,
               janela de IPOs, notícias, debate bull/bear) ──► IpoSynthesis ──► memória ──► Telegram

I.3 ipo_lifecycle_agent ──► para ações cotadas há < 1 ano: eventos pós-IPO ──► 2.14 calendário, 2.15 timing, 2.19
```

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

**GDELT DOC API** — respondeu 429 ao primeiro pedido; **com 10 s de espera funcionou** (2 artigos em 24 h num sábado). Fonte secundária, com espaçamento.

**Outras verificações da Fase 0 (2026-11-14)**
- **Futuros e índices (yfinance, 5 min):** `ES=F`, `NQ=F` (quase 24 h: 1304 barras em 5 dias), `^GSPC`, `^STOXX50E`, `^GDAXI`, `^N225`, `^KS11`, `^HSI`, `000001.SS` ✅.
- **`yf.Search` encontra cotações cruzadas** ✅: Alibaba → `BABA`, `9988.HK`; Samsung → `005930.KS`, GDR `SMSN.IL` (Londres); Toyota → `TM`, `7203.T`.
- **`upgrades_downgrades` (EUA) traz preço-alvo por casa** ✅: `currentPriceTarget`, `priorPriceTarget`, `priceTargetAction`.
- **`exchange_calendars` 4.13.2** ✅ — sessões em UTC com pausas e horário de verão (ver secção 4). Shenzhen não tem calendário próprio (`XSHE` não existe) → usar `XSHG`.
- **`pandas-ta-classic` 0.9.0** ✅ — RSI e MACD calculados sobre AAPL.
- **akshare, histórico A-share:** ❌ o Eastmoney limitou o IP temporariamente (ver D15).

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
| ~~Sem horários das sessões via API~~ | 2.5, 2.6 | ✅ resolvido: `exchange_calendars` (D14) |
| Ações com pouco histórico (IPOs recentes) | 2.7, 2.8, 2.9, 2.18 | `profile_agent` marca `ipo_recente`; cada agente usa só o que o histórico permite (ex.: sem SMA 200 abaixo de 200 sessões) e o forecast alarga os intervalos |
| Sem scores (Piotroski, Altman) nem DCF fora dos EUA | 2.7, 2.9 | EUA: FMP; resto: script próprio com pressupostos explícitos (validado contra o FMP nas ações dos EUA) |
| FMP: 250 chamadas/dia | todos os que usam FMP | cache com TTL, contador diário no SQLite, fallback para yfinance ao esgotar |

### 3.3 Repositórios a reutilizar

| Repo | Uso | Estado |
|---|---|---|
| [yfinance](https://github.com/ranaroussi/yfinance) | fonte principal, todos os mercados | ✅ verificado |
| [akshare](https://github.com/akfamily/akshare) | China/HK: notícias em chinês, dados A-share | ✅ notícias verificadas; o resto a verificar |
| [pandas-ta-classic](https://pypi.org/project/pandas-ta-classic/) | indicadores técnicos (fork mantido; o `pandas-ta` original anuncia arquivo) | ✅ 0.9.0 |
| exchange_calendars | horários, pausas e feriados de todas as bolsas | ✅ 4.13.2 |
| Skills `bigdata-pre-ipo-analysis` e `bigdata-post-ipo-day1/14/179/365` (plugin bigdata-com já instalado) | **metodologia** para as skills de IPO: estrutura da oferta tirada do prospeto, "não divulgado" em vez de estimativas, comparáveis com múltiplos, janela de IPOs, lock-up com matemática de float/overhang | reescrita nas nossas skills; as tools Bigdata.com não são usadas. Diferença: as deles não classificam, as nossas sim (D13) |
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
**Calendário de IPOs:** Finnhub `calendar/ipo` ✅ (17 IPOs nas semanas seguintes, com data, bolsa, intervalo de preço, nº de ações e valor; cobertura internacional a verificar) · Alpha Vantage `IPO_CALENDAR` ✅ (CSV, EUA) · FMP e EODHD ❌ (pagos) · China: akshare (a verificar) · HK, Coreia, Japão, Europa: web.

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

**Horários confirmados com `exchange_calendars` (D14)** — sessões em UTC:

| Bolsa | Inverno (16-nov) | Verão (15-jul) | Pausa (UTC) |
|---|---|---|---|
| XNYS (Nova Iorque) | 14:30–21:00 | 13:30–20:00 | — |
| XETR, XAMS, XLON, XSWX | 08:00–16:30 | 07:00–15:30 | — |
| XTKS (Tóquio) | 00:00–06:30 | 00:00–06:30 | 02:30–03:30 |
| XKRX (Coreia) | 00:00–06:30 | 00:00–06:30 | — |
| XHKG (Hong Kong) | 01:30–08:00 | 01:30–08:00 | 04:00–05:00 |
| XSHG (Xangai; usar também para Shenzhen) | 01:30–07:00 | 01:30–07:00 | 03:30–05:00 |

A Ásia não muda de hora; a Europa e os EUA sim — por isso a sobreposição entre sessões muda ao longo do ano e é sempre calculada, nunca fixada.

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
| 0.2 | `profile_agent` **(novo)** | S | yf info/fast_info, yf Search ✅ | ref cross_listings.yaml, exchange_calendars; marca `ipo_recente` | 7 dias | — |
| 2.1 | `news_4_hours_agent` | L | WebSearch/WebFetch, yf news, akshare (China), GDELT | sk news-triage, sc check_window + dedupe, ref sources_by_market, tp | sempre fresco | 0.2 |
| 2.2 | `news_24_hours_agent` | L | idem (herda `news_base`) | idem | 1 h | 0.2 |
| 2.3 | `news_7_days_agent` | L | idem | idem | 6 h | 0.2 |
| 2.4 | `news_30_days_agent` | L | idem | idem | 24 h | 0.2 |
| 2.5a | `asia_lead_agent` **(novo)** | S | yf intraday: própria ação noutra bolsa, peers asiáticos, ^N225 ^KS11 ^HSI 000001.SS | sc session_map (exchange_calendars), ref proxies.yaml | 15 min | 0.2 |
| 2.5 | `europe_lead_agent` | S | yf intraday: cotação europeia, peers europeus, ^STOXX50E ^GDAXI | idem | 15 min | 0.2 |
| 2.6 | `us_lead_agent` | S | yf: fecho e after-hours dos EUA, ADR, ^GSPC ^IXIC, futuros ES=F NQ=F ✅ | idem | 15 min | 0.2 |
| 2.7 | `health_momentum_agent` | S | yf demonstrações + info + EOD + índice local | sc scores (Piotroski, Altman, momentum) | 1 dia | 0.2 |
| 2.8 | `technical_agent` | S+L | yf EOD + intraday | sc indicators (pandas-ta-classic), sk technical-reading | 1 dia | 0.2 |
| 2.9 | `fundamental_agent` | S+L | yf demonstrações, info | sc valuation (DCF próprio, múltiplos vs peers), sk fundamental-framework | 1 dia | 0.2, 2.12 |
| 2.10 | `sentiment_agent` | L | 2.1–2.4, 2.16, fluxos Coreia (opcional) | sk sentiment-rubric | por execução | 2.1–2.4, 2.16 |
| 2.11 | `market_share_agent` | S+L | web + receitas dos peers (yf) | sk, ref | 30 dias, por indústria | 0.2, 2.12 |
| 2.12 | `competitors_agent` | S+L | LLM propõe peers → screener yf valida → script compara | sc comps, sub peer_validator | 1 dia, por indústria | 0.2 |
| 2.13 | `relations_agent` | L | SEC, DART, CNINFO/akshare, web | sk, ref filings_by_market | 30 dias | 0.2 |
| 2.14 | `calendar_agent` | S | yf calendar, earnings dates; eventos pós-IPO de I.3 | — | 1 dia | 0.2, I.3 |
| 2.15 | `timing_agent` | L | 2.5a, 2.5, 2.6, 2.8, 2.10, 2.14 | sk timing-rules (incl. limites diários) | por execução | camada 2 |
| 2.16 | `analysts_agent` | S (+L fora dos EUA) | yf recommendations; upgrades_downgrades (EUA); web | — | 1 dia | 0.2 |
| 2.17 | `price_targets_agent` | S (+L fora dos EUA) | yf analyst_price_targets (atual/mín/máx/média/mediana); alvos por casa (EUA); web | — | 1 dia | 0.2 |
| 2.18 | `forecast_agent` | S+L | volatilidade (script), 2.8, 2.9, 2.17 | sc ranges, sk scenarios | por execução | camada 2 |
| 2.19 | `rating_agent` | L | tudo | sub bull + bear + juiz, sk rating-rubric, hk anti-alucinação | por execução | 2.15, 2.18 |
| 3 | `memory_agent` ✅ | S | SQLite | — | — | 2.19 |
| 4 | `change_alert_agent` ✅ | S | SQLite, Telegram | sc diff de razões | — | 3 |
| — | `eval_agent` **(novo)** | S | histórico + EOD | tp relatório | — | 3 |
| I.1 | `ipo_calendar_agent` **(novo)** | S | Finnhub `calendar/ipo` ✅, Alpha Vantage `IPO_CALENDAR` ✅, akshare (China, a verificar), web (HK, Coreia, Japão, Europa) | sc normalização + dedupe + limiar de dimensão | 12 h | — |
| I.2 | `pre_ipo_agent` **(novo)** | L | prospeto (SEC S-1/F-1 via EDGAR, DART, HKEXnews, CNINFO), notícias, peers cotados (2.12), desempenho dos IPOs recentes do setor | sk pre-ipo-analysis, sc deal_math, sub bull + bear + juiz (os do 2.19) | 1 dia | I.1 |
| I.3 | `ipo_lifecycle_agent` **(novo)** | S | prospeto (lock-up), yf (data de estreia, histórico), calendário de resultados | sk post-ipo-lifecycle | 1 dia | 0.2 |

**Ações dos EUA (e ADRs cobertos):** o router de dados usa primeiro o FMP em 0.2 (peers), 2.7 (financial-scores), 2.9 (métricas, rácios, DCF, estimativas), 2.11 (segmentação de receitas), 2.12 (peers), 2.14 (histórico de resultados com surpresas), 2.16 (grades por casa) e 2.17 (price-target summary). Nos restantes mercados, e se o FMP falhar, usa as fontes da tabela.

### Notas por agente

- **0.2 profile_agent (novo):** quase todos os agentes precisam de saber a bolsa, o mercado, a moeda, o setor e as outras cotações (ADR, A/H, GDR). Resolve-se uma vez e passa a ser o contexto do resto. Para as outras cotações: tabela manual dos pares conhecidos (`cross_listings.yaml`) + pesquisa do yfinance.
- **2.1–2.4 notícias:** um pacote base `agents/_shared/news_base/` (prompt, skill, scripts, schema). Os quatro agentes são `agent.yaml` finos com `extends: news_base` e a sua janela/TTL. Mantêm-se separados porque cada janela tem estratégia diferente: 4 h = notícias de última hora, sempre fresco; 30 dias = só os acontecimentos marcantes, em cache 24 h.
- **2.5a / 2.5 / 2.6 sinais entre sessões:** um motor genérico (`session_map`) usa o `exchange_calendars` para saber, no momento do trigger, que bolsas estão abertas ou fechadas em relação à bolsa principal da ação. Sinais por ordem de força: (1) a própria ação noutra bolsa, (2) futuros do índice, (3) peers do setor na sessão que lidera, (4) índice dessa sessão. Saída: variação desde o fecho da bolsa principal, por proxy, com peso e confiança. Sem proxy relevante → `applicable: false`, sem ruído.
- **2.8 técnica:** o script calcula SMA 50/200, EMA, RSI, MACD, ATR, Bollinger, volume relativo, suportes e resistências (pivots), e marca proximidade aos limites diários (China, Coreia). O LLM só lê o JSON.
- **2.12 concorrentes:** sem lista de peers na fonte, o LLM propõe e um subagente valida com o screener (mesma indústria, dimensão comparável) antes de o script montar a tabela de comparáveis.
- **2.18 forecast:** cenários e não preço pontual — bear/base/bull com intervalos a 1, 3 e 12 meses. O intervalo estatístico vem de script (volatilidade histórica); a ancoragem vem dos preços-alvo e do DCF.
- **2.19 classificação:** v1 = um só LLM com rubrica (linha de base). v2 = subagente bull + subagente bear + juiz. Um hook valida que os números citados nas razões existem nos inputs.
- **4 change_alert_agent:** a mensagem de Telegram passa a incluir o que mudou nas razões face à classificação anterior (diff por código, ver D6).
- **I.1 ipo_calendar_agent:** IPOs dos próximos N dias, nos mercados cobertos, acima de um limiar de dimensão (configurável, ex.: ≥ 1 mil M USD). Exclui SPACs por omissão (aparecem no calendário, ex.: "Acquisition Corp."). Alerta Telegram quando entra um IPO novo acima do limiar.
- **I.2 pre_ipo_agent:** metodologia adaptada das skills bigdata (secção 3.3): estrutura da oferta **do prospeto** (intervalo de preço, ações primárias/secundárias, greenshoe, subscritores, lock-up, classes de ações, uso dos fundos); "não divulgado" em vez de estimar; o script `deal_math` calcula a valorização implícita (preço × ações pós-oferta), o free float e os múltiplos vs peers cotados; janela de IPOs = desempenho dos IPOs recentes do setor. Classificação própria **Subscrever / Neutro / Evitar** + confiança, com debate bull/bear. Gravada na memória com tipo `ipo`.
- **I.3 ipo_lifecycle_agent:** para ações cotadas há menos de 1 ano, calcula as datas que mexem com o preço: estreia, fim do período de silêncio (~25 dias nos EUA → início da cobertura de analistas), primeiros resultados, **fim do lock-up tirado do prospeto** (nunca assumir 180 dias; atenção a libertações antecipadas), 1 ano. Para o lock-up: ações libertadas, aumento do free float, dias de negociação para absorver (ações libertadas / volume médio). Alerta Telegram 7 dias antes de um fim de lock-up numa ação do histórico.

---

## 6. Fases

Ordem pensada para ter **uma ação a dar classificação de ponta a ponta o mais cedo possível** (Fase 2) e depois alargar.

### Fase 0 — Verificações e fundações
| Tarefa | Aceitação |
|---|---|
| ~~Cobertura de fontes por mercado~~ | ✅ feito (secção 3.1) |
| ~~Cobertura do plano FMP~~ | ✅ feito (secção 3.1) |
| ~~Chaves dos fornecedores complementares + `probe_providers.py`~~ | ✅ feito (secção 3.4); falta só GuruFocus |
| ~~Futuros, `yf.Search`, alvos em `upgrades_downgrades`, `exchange_calendars`, pandas-ta-classic, GDELT~~ | ✅ feito (secção 3.1) |
| ~~Horários das bolsas~~ | ✅ `exchange_calendars` (D14, secção 4); deixa de ser preciso o `all-exchange-market-hours` do FMP |
| ~~Fontes de calendário de IPOs~~ | ✅ Finnhub e Alpha Vantage (secção 3.4) |
| akshare para dados A-share além das notícias | repetir depois do limite do Eastmoney passar (D15) |
| ~~`git init` + primeiro commit~~ | ✅ |
| ~~Carregar `.env` (`python-dotenv`)~~ | ✅ `core/env.py` |
| ~~Bot Telegram~~ | ✅ `@agentock_bot`, mensagem de teste recebida |
| ~~Primeira execução real do `news_4_hours_agent`~~ | ✅ AAPL 4 h ao sábado: 0 notícias (não inventa); Samsung 48 h: 2 notícias reais, incluindo fonte coreana; AAPL 48 h via orquestrador: 9 notícias, $0,31, 42 s |

### Fase 1 — Motor
| Tarefa | Aceitação |
|---|---|
**✅ Concluída em 2026-11-14.** 29 testes unitários + teste real (`tools/smoke_data.py`) + execução LLM ponta a ponta.

| Tarefa | Estado |
|---|---|
| `core/data/`: fornecedores (`providers/yfinance_p.py`, `providers/keyed.py` — 11 fornecedores), `http.py` (retries, classificação 401/402/403/404/429 e erros no corpo), `store.py` (cache com TTL + livro de quotas em `data/cache.db`), `markets.py` | ✅ 27/27 fornecedor×capacidade a funcionar no teste real |
| `config/data_sources.yaml`: quotas por fornecedor, rotas por dado × mercado, TTL, capacidades em "merge" | ✅ editável sem tocar em código |
| `core/data/router.py`: prioridade, cache, quotas (minuto/hora/dia/mês), memória de bloqueios (7 dias), pausa após 429, merge+dedupe de notícias e IPOs, `cross_check_close` | ✅ fechos AAPL/Moutai/Samsung batem a 0,0% entre 2 fontes |
| Servidor MCP in-process `market` (`core/market_tools.py`, 13 tools) | ✅ o `news_4_hours_agent` chamou `mcp__market__news` e `profile` numa execução real |
| `agent.yaml` alargado: `extends`, `kind`, `model`, `effort`, `max_budget_usd`, `market_tools`, `hooks`, `subagents`, `cache_ttl`, **`cache_key`** (lista de inputs que definem a chave — substitui o `cache_scope` previsto: para cache por indústria basta `cache_key: [industry]`) | ✅ testes do loader (herança, ficheiros do pai, herança circular) |
| Cache de outputs no runner | ✅ teste: 2.ª execução vem da cache; `--no-cache` ignora |
| `core/hooks.py`: `log_tools` (sempre ligado, `data/logs/<run_id>.jsonl`), `block_domains`, `mcp_quota` | ✅ log real gerado; domínio bloqueado recusado em teste |
| Orquestrador DAG (`core/orchestrator.py` + `flow.yaml`): dependências deduzidas das referências `$nó.campo`, camadas em paralelo, timeout por nó, falha isolada | ✅ testes (ordem, ciclo, timeout, falha isolada) |
| Tabela `agent_outputs` (run_id, nó, agente, ticker, output, custo, duração, turnos, cache) | ✅ |
| CLI: `--only`, `--no-cache`, `--dry-run`, `--flow` | ✅ |
| Corrigido: `RuntimeError: aclose()` (o runner fazia `return` dentro do `async for`) | ✅ |

Notas: os testes do router usam fornecedores falsos em vez de respostas gravadas; a cobertura real fica no `tools/smoke_data.py`. A Alpaca e o Tiingo só têm o feed IEX (candles intraday esparsos), por isso o yfinance passou a primeiro no intraday dos EUA; a Alpaca fica primeira na cotação em tempo real.

### Fase 2 — Fatia vertical (marco M1)
Agentes: 0.2 profile, 2.1 news_4h, 2.8 técnica, 2.14 calendário, 2.16 analistas, 2.17 preços-alvo, 2.19 classificação v1 → memória → alerta.

**Aceitação M1:** `python flow.py AAPL` e `python flow.py 005930.KS` produzem uma classificação gravada; uma segunda execução com mudança dispara Telegram; custo e tempo por agente visíveis.

### Fase 3 — Dados restantes
2.5a asia_lead, 2.5 europe_lead, 2.6 us_lead, 2.7 health_momentum, 2.9 fundamental, **I.1 ipo_calendar, I.3 ipo_lifecycle** (scripts; I.3 alimenta o 2.14).
**Aceitação:** testes com fixtures; corre para um ticker de cada mercado da secção 4; `applicable: false` quando não há proxy; pares A/H e ADR detetados; `python flow.py --ipos` lista os IPOs dos próximos 30 dias sem SPACs; uma ação cotada há menos de 1 ano mostra as datas pós-IPO no calendário.

### Fase 4 — Notícias completas e sentimento
Refatorar para `news_base`; 2.2, 2.3, 2.4; pesquisa multilíngue; script de deduplicação; 2.10 sentimento.
**Aceitação:** a mesma notícia não aparece duplicada entre fontes; cada janela respeita o seu TTL; notícias chinesas e coreanas aparecem para ações desses mercados.

### Fase 5 — Análise competitiva
2.11 quota de mercado, 2.12 concorrentes, 2.13 parceiras/subsidiárias, com cache por indústria.
**Aceitação:** duas ações da mesma indústria reutilizam a mesma análise de setor.

### Fase 6 — Síntese completa
2.15 timing, 2.18 forecast, 2.19 v2 (debate bull/bear + juiz), hook anti-alucinação, guardrail "análise, não aconselhamento personalizado", diff de razões no alerta.
**Aceitação:** as razões citam só números presentes nos inputs; a classificação inclui confiança e o que falhou a montante.

### Fase 6b — IPOs
I.2 pre_ipo_agent (skill pre-ipo-analysis, script deal_math, debate reutilizado do 2.19); classificação Subscrever / Neutro / Evitar gravada na memória (tipo `ipo`); alertas Telegram de IPO novo acima do limiar e de fim de lock-up a 7 dias; trigger `python flow.py --ipo "Nome"`.
**Aceitação:** para um IPO real próximo, a análise tira a estrutura da oferta do prospeto, escreve "não divulgado" onde falta, e a valorização implícita bate com preço × ações pós-oferta.

### Fase 7 — Avaliação
`python flow.py --backfill` preenche retornos a 1, 7 e 30 dias; `eval_agent` gera relatório de acerto por classificação, por nível de confiança, por mercado e por versão (v1 vs v2), contra o índice local. **IPOs:** classificação vs retorno desde o preço do IPO até ao fecho do dia 1, dia 30 e dia 180.
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
| akshare/Eastmoney limita o IP | fonte secundária, backoff longo, nunca primária (D15) |
| Calendário de IPOs fora dos EUA fraco nas APIs grátis | web (LLM) com fontes oficiais (HKEX, KIND, JPX, CNINFO) na skill; medir a cobertura na Fase 6b |
| Dados do prospeto mal extraídos | `deal_math` confere a consistência (valorização = preço × ações pós-oferta); "não divulgado" em vez de estimar |

---

## 9. Decisões em aberto

Nenhuma de momento. Pendências do utilizador: chave OpenDART (`DART_API_KEY`); token GuruFocus só se houver Premium.
