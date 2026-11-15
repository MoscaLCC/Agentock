"""Progresso de uma análise para o Telegram: uma única mensagem que se vai editando (etapas, percentagem, ETA).

O orquestrador emite eventos (`start`/`done` por nó); aqui agrupam-se em 6 etapas com nomes de gente e estima-se o
tempo que falta pelo caminho mais longo do que ainda não acabou, com as durações médias medidas (BASELINE §3).
"""
import time

from . import messages as M

STAGES = [
    ("Empresa e cotação", ("profile",)),
    ("Preços, contas e analistas", ("indicators", "ipo_lifecycle", "calendar", "analysts", "price_targets", "health",
                                    "asia_lead", "europe_lead", "us_lead", "insiders", "comps", "fundamental_data",
                                    "forecast_stats")),
    ("Notícias e sentimento", ("news_feed", "news_scan", "news", "sentiment")),
    ("Concorrentes e setor", ("competitors", "market_share", "relations")),
    ("Leituras e cenários", ("technical", "fundamental", "timing", "forecast")),
    ("Debate e classificação", ("dossier", "bull", "bear", "rating", "guard", "memory", "alert")),
]
# segundos esperados por nó numa análise fria (os scripts ficam em 2 s por omissão)
EXPECTED = {"profile": 3, "comps": 6, "insiders": 4, "news_feed": 3, "news_scan": 22, "competitors": 20,
            "market_share": 30, "relations": 28, "technical": 11, "fundamental": 11, "timing": 14, "forecast": 18,
            "bull": 9, "bear": 9, "rating": 20, "news": 1, "sentiment": 1, "dossier": 1, "guard": 1, "memory": 1,
            "alert": 2}
DEFAULT_EXPECTED = 2


class Progress:
    def __init__(self, title: str, order: list[str], deps: dict[str, set[str]], expected: dict | None = None,
                 clock=time.time):
        self.title, self.order, self.deps, self.clock = title, order, deps, clock
        self.expected = {**EXPECTED, **(expected or {})}
        self.started: dict[str, float] = {}
        self.done: dict[str, str] = {}      # nó → estado
        self.t0 = clock()

    def on_event(self, e: dict) -> None:
        if e.get("type") == "start":
            self.started.setdefault(e["node"], self.clock())
        elif e.get("type") == "done":
            self.done[e["node"]] = e.get("status") or "ok"

    def _exp(self, node: str) -> float:
        return float(self.expected.get(node, DEFAULT_EXPECTED))

    def eta(self) -> float:
        """Segundos que faltam: caminho mais longo pelos nós por acabar."""
        now, finish = self.clock(), {}
        for n in self.order:  # ordem topológica
            start = max((finish.get(d, 0.0) for d in self.deps.get(n, ())), default=0.0)
            if n in self.done:
                finish[n] = 0.0
            elif n in self.started:
                finish[n] = max(1.0, self._exp(n) - (now - self.started[n]))
            else:
                finish[n] = start + self._exp(n)
        return max(finish.values(), default=0.0)

    def fraction(self) -> float:
        total = sum(self._exp(n) for n in self.order) or 1.0
        return min(1.0, sum(self._exp(n) for n in self.done) / total)

    def stage_marks(self) -> list[tuple[str, str]]:
        """(marca, nome) por etapa: ✅ acabada · ▶️ a correr · ⬜ por começar."""
        out = []
        for name, nodes in STAGES:
            mine = [n for n in nodes if n in self.order]
            if not mine:
                continue
            if all(n in self.done for n in mine):
                mark = "✅"
            elif any(n in self.started or n in self.done for n in mine):
                mark = "▶️"
            else:
                mark = "⬜"
            out.append((mark, name))
        return out

    def text(self, queued_behind: int = 0) -> str:
        frac = self.fraction()
        filled = round(frac * 10)
        left = self.eta()
        head = f"⏳ <b>A analisar {M.esc(self.title)}</b>"
        bar = f"{'▓' * filled}{'░' * (10 - filled)} {frac:.0%}" + (f" · faltam ~{M.duration_pt(left)}" if left >= 5 else "")
        lines = [head, bar, ""] + [f"{mark} {name}" for mark, name in self.stage_marks()]
        lines += ["", "/cancelar para parar" + (f" · {queued_behind} em fila a seguir" if queued_behind else "")]
        return "\n".join(lines)
