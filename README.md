# ChessCoach

Coach d'échecs personnalisé, opensource, local et gratuit, construit à partir de
vos parties Chess.com. Principe non négociable : **le LLM formule, il ne juge
jamais** — chaque fait sur une position vient de Stockfish ou de python-chess.

État : **phase 0 — corpus** (ingestion + taxonomie figée).

## Installation

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Ingestion des parties Chess.com

```bash
python -m chesscoach.ingest.chesscom <username> --db data/chesscoach.sqlite
python -m chesscoach.ingest.chesscom <username> --since 2025-01 --until 2025-06
```

Chaque mois d'archive est téléchargé une seule fois (table `archive_months`) ;
relancer la commande ne crée pas de doublons.

## Requêter le corpus

```bash
sqlite3 data/chesscoach.sqlite \
  "select time_class, count(*) from games group by time_class;"
```

## Tests

```bash
pytest
```

Les tests de phase 0 tournent sans Stockfish, sans LLM et sans réseau.

## Documentation

- `docs/decisions.md` — journal des décisions de conception (taxonomie, schéma…).
