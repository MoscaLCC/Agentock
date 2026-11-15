"""Erros em linguagem humana, com o próximo passo. O texto técnico fica no registo; ao telemóvel chega isto.

classify(erro) → tipo:
  limit      limite de utilização da subscrição do Claude atingido (com a hora de reposição, se vier no erro)
  auth       login do Claude expirado / chave inválida
  credit     créditos da API esgotados (modo AGENTOCK_CLAUDE_AUTH=api)
  timeout    um passo excedeu o tempo
  no_data    nenhum fornecedor tem os dados
  network    sem rede
  ambiguous  o pedido corresponde a várias empresas
  not_found  não há nenhuma cotação ativa para o pedido
  cancelled  cancelado pelo utilizador
  skipped    consequência de outro passo ter falhado (não é a causa)
  other
"""
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LISBON = ZoneInfo("Europe/Lisbon")
PATTERNS = [
    ("limit", re.compile(r"hit your .{0,20}limit|usage limit|rate.?limit|limite de utiliza|\b429\b", re.I)),
    ("auth", re.compile(r"please run /login|login expired|invalid api key|authentication|unauthorized|\b401\b|oauth", re.I)),
    ("credit", re.compile(r"credit balance is too low|insufficient credit", re.I)),
    ("cancelled", re.compile(r"cancelad", re.I)),
    ("timeout", re.compile(r"^timeout|timed out|TimeoutError", re.I)),
    ("ambiguous", re.compile(r"é ambíguo", re.I)),
    ("not_found", re.compile(r"não encontrei nenhuma cotação", re.I)),
    ("no_data", re.compile(r"DataUnavailable|nenhum fornecedor respondeu|sem recolha das APIs", re.I)),
    ("network", re.compile(r"ConnectionError|URLError|getaddrinfo|Max retries|HTTPSConnectionPool|sem ligação|"
                           r"Temporary failure|NameResolution", re.I)),
    ("skipped", re.compile(r"sem dados de entrada", re.I)),
]
RESET = re.compile(r"resets?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?(?:\s*\(([^)]+)\))?", re.I)

# nome de cada nó em linguagem de gente, e o que se perde quando falha
NODE_LABEL = {
    "profile": "empresa e cotação", "indicators": "indicadores técnicos", "technical": "leitura técnica",
    "calendar": "calendário de resultados", "analysts": "consenso dos analistas", "price_targets": "preços-alvo",
    "health": "saúde financeira", "fundamental_data": "contas e valorização", "fundamental": "leitura fundamental",
    "competitors": "concorrentes", "comps": "comparação com concorrentes", "market_share": "quotas de mercado",
    "relations": "empresas relacionadas", "ipo_lifecycle": "ciclo pós-IPO", "asia_lead": "sinais da Ásia",
    "europe_lead": "sinais da Europa", "us_lead": "sinais dos EUA", "insiders": "transações de insiders",
    "news_feed": "recolha de notícias", "news_scan": "triagem de notícias", "news": "notícias",
    "sentiment": "sentimento", "timing": "momento de entrada", "forecast_stats": "intervalos de preço",
    "forecast": "cenários", "dossier": "dossier", "bull": "caso a favor", "bear": "caso contra",
    "rating": "classificação", "guard": "verificação dos números", "memory": "histórico", "alert": "alerta",
}


def classify(error: str | None) -> str:
    e = error or ""
    return next((kind for kind, rx in PATTERNS if rx.search(e)), "other")


def reset_time(error: str | None, now: datetime | None = None) -> datetime | None:
    """'… resets 8am (Europe/Lisbon)' → próxima ocorrência dessa hora (UTC)."""
    m = RESET.search(error or "")
    if not m:
        return None
    hour, minute, ampm, tz = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower(), m.group(4)
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    try:
        zone = ZoneInfo(tz) if tz else LISBON
    except Exception:  # noqa: BLE001
        zone = LISBON
    now = (now or datetime.now(timezone.utc)).astimezone(zone)
    when = now.replace(hour=hour % 24, minute=minute, second=0, microsecond=0)
    if when <= now:
        when += timedelta(days=1)
    return when.astimezone(timezone.utc)


def hhmm(when: datetime | None) -> str:
    return when.astimezone(LISBON).strftime("%H:%M") if when else "daqui a pouco"


def root_cause(problems: dict) -> tuple[str | None, str | None, str]:
    """(nó, erro, tipo) da causa de uma análise sem classificação: o 1.º problema que não é consequência de outro."""
    for node, res in problems.items():
        kind = classify(getattr(res, "error", None))
        if kind != "skipped":
            return node, getattr(res, "error", None), kind
    node, res = next(iter(problems.items()), (None, None))
    return node, getattr(res, "error", None), "other"


def humanize(kind: str, *, subject: str = "", error: str | None = None, node: str | None = None,
             now: datetime | None = None) -> str:
    """Texto para o utilizador (sem HTML). `subject`: nome ou ticker da ação."""
    what = f" da {subject}" if subject else ""
    step = NODE_LABEL.get(node or "", node or "um passo")
    if kind == "limit":
        return (f"⏸️ Atingi o limite de utilização do Claude. A análise{what} parou em «{step}»; o que já foi "
                f"recolhido fica guardado. O limite repõe às {hhmm(reset_time(error, now))} e eu retomo sozinho.")
    if kind == "auth":
        return ("🔑 A sessão do Claude expirou. No PC, abre um terminal e corre `claude /login`; "
                "depois toca em Repetir.")
    if kind == "credit":
        return ("💳 Os créditos da API do Claude acabaram. Carrega créditos, ou muda para a subscrição "
                "(AGENTOCK_CLAUDE_AUTH=subscription no .env), e toca em Repetir.")
    if kind == "timeout":
        return f"⏱️ A análise{what} parou em «{step}» por excesso de tempo. O resto ficou guardado; toca em Repetir."
    if kind == "no_data":
        return f"📭 Nenhum fornecedor tem dados para «{step}»{what}. A análise não pôde ser concluída."
    if kind == "network":
        return f"📡 Sem ligação aos fornecedores de dados durante «{step}». Verifica a rede e toca em Repetir."
    if kind == "cancelled":
        return f"🛑 Análise{what} cancelada. O que já foi recolhido fica guardado."
    return f"⚠️ A análise{what} falhou em «{step}». O erro ficou registado; toca em Repetir ou vê /estado."


def gaps_text(problems: dict) -> str | None:
    """Passos sem resultado numa análise que terminou: o que faltou e o efeito."""
    names = [NODE_LABEL.get(n, n) for n, r in problems.items() if n not in ("memory", "alert")]
    if not names:
        return None
    shown = ", ".join(names[:4]) + (f" e mais {len(names) - 4}" if len(names) > 4 else "")
    return f"⚠️ Sem dados de: {shown}. A classificação conta com isso como lacuna (menos confiança)."
