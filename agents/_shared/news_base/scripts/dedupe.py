"""Agrupa notícias quase iguais (mesmo URL canónico ou títulos muito parecidos).

Uso: python scripts/dedupe.py --json '[{"title": "...", "url": "..."}, ...]' [--threshold 0.75]
Saída: JSON [[índices do grupo 1], [índices do grupo 2], ...] — fica uma notícia por grupo (a mais primária).
"""
import argparse
import json
import re
from difflib import SequenceMatcher


def canon(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", (url or "").split("?")[0].split("#")[0]).rstrip("/").lower()


def norm(title: str) -> str:
    return re.sub(r"[^\w\s]", " ", (title or "").lower()).strip()


def groups(items: list[dict], threshold: float = 0.75) -> list[list[int]]:
    out: list[list[int]] = []
    for i, it in enumerate(items):
        for g in out:
            ref = items[g[0]]
            same_url = canon(it.get("url")) and canon(it.get("url")) == canon(ref.get("url"))
            similar = SequenceMatcher(None, norm(it.get("title")), norm(ref.get("title"))).ratio() >= threshold
            if same_url or similar:
                g.append(i)
                break
        else:
            out.append([i])
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--json", required=True)
    p.add_argument("--threshold", type=float, default=0.75)
    a = p.parse_args()
    print(json.dumps(groups(json.loads(a.json), a.threshold)))
