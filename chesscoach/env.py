"""Chargement optionnel d'un fichier ``.env`` à la racine du projet (jamais versionné).

Format ``CLE=valeur``, une par ligne, ``#`` pour les commentaires. Les variables déjà présentes dans
l'environnement ont priorité : le fichier ne remplace rien, il complète.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path | None = None) -> dict[str, str]:
    """Charge ``.env`` si présent ; retourne les variables effectivement ajoutées."""
    path = path or ROOT / ".env"
    added: dict[str, str] = {}
    if not path.is_file():
        return added
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value
            added[key] = value
    return added
