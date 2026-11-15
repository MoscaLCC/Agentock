"""Dossier compacto (core/dossier.py)."""
from core import dossier


def run(**sections):
    return dossier.build(sections)
