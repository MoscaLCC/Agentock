"""Verifica se timestamps ISO 8601 estão dentro das últimas N horas.

Uso: python scripts/check_window.py --hours 4 2026-11-14T09:30:00Z 2026-11-13T02:00:00+00:00
Saída: JSON [{"ts": ..., "inside": true|false|null, "age_hours": float|null}]
"""
import argparse
import json
from datetime import datetime, timedelta, timezone


def parse(ts: str):
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


p = argparse.ArgumentParser()
p.add_argument("--hours", type=float, default=4)
p.add_argument("timestamps", nargs="+")
a = p.parse_args()

now = datetime.now(timezone.utc)
out = []
for ts in a.timestamps:
    d = parse(ts)
    if d is None:
        out.append({"ts": ts, "inside": None, "age_hours": None})
        continue
    age = (now - d).total_seconds() / 3600
    out.append({"ts": ts, "inside": timedelta(0) <= now - d <= timedelta(hours=a.hours),
                "age_hours": round(age, 2)})
print(json.dumps(out))
