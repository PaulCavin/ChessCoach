# ChessCoach

Coach d'échecs personnalisé, opensource, local et gratuit, construit à partir de
vos parties Chess.com. Principe non négociable : **le LLM formule, il ne juge
jamais** — chaque fait sur une position vient de Stockfish ou de python-chess.

État : **phase 1 — analyse** (moteur, classification, rapport agrégé sans LLM).

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

## Analyse moteur et rapport

Stockfish : binaire dans `bin/stockfish-bin` (ou `$CHESSCOACH_STOCKFISH`, ou dans le PATH).

```bash
# 1. une éval Stockfish par position (profondeur 14, 4 processus), idempotent
python -m chesscoach.engine.analyse --username <username> --time-class rapid --time-control 600 --workers 4
# 2. moments critiques classés dans la taxonomie (recalculé à chaque fois)
python -m chesscoach.taxonomy.classify_games --username <username>
# 3. rapport Markdown
python -m chesscoach.report --username <username> --time-class rapid --time-control 600 --out reports/<username>.md
```

## Bilan visuel et explications

```bash
# pages HTML autonomes (échiquiers SVG, flèches, courbe d'éval) pour les 10 dernières parties
python -m chesscoach.report.html --username <username> --games 10 --out reports/html
# explication d'un moment critique par le LLM, vérifiée par le critique
export CHESSCOACH_LLM_PROVIDER=deepseek DEEPSEEK_API_KEY=...   # ou ollama (défaut), anthropic
python -m chesscoach.agents.explainer --game 1287 --ply 55
```

## Requêter le corpus

```bash
sqlite3 data/chesscoach.sqlite \
  "select time_class, count(*) from games group by time_class;"
```

## Tests

```bash
pytest
```

Les tests tournent sans LLM et sans réseau ; un seul test utilise Stockfish et est sauté s'il est absent.

## Documentation

- `docs/decisions.md` — journal des décisions de conception (taxonomie, schéma…).
