"""Emplacements des données locales (aucune donnée n'est envoyée sur le réseau)."""

from __future__ import annotations

import os
from pathlib import Path


def app_home() -> Path:
    """Répertoire de données de l'application.

    Surchargeable via la variable d'environnement ``LRL_HOME`` (tests, profils portables).
    """
    env = os.environ.get("LRL_HOME")
    base = Path(env) if env else Path.home() / ".lunatic_radio_lab"
    base.mkdir(parents=True, exist_ok=True)
    return base


def subdir(name: str) -> Path:
    p = app_home() / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def database_path() -> Path:
    return app_home() / "lunatic_radio_lab.sqlite3"


def imports_dir() -> Path:
    return subdir("imports")


def captures_dir() -> Path:
    return subdir("captures")


def reports_dir() -> Path:
    return subdir("reports")


def logs_dir() -> Path:
    return subdir("logs")
