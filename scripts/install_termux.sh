#!/usr/bin/env sh
# Installation complète sous Termux (Android). À lancer depuis le dossier du projet.
set -eu
cd "$(dirname "$0")/.."
pkg update -y
pkg install -y python git stockfish
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
mkdir -p bin && ln -sf "$(command -v stockfish)" bin/stockfish
[ -f .env ] || cp .env.example .env
echo
echo "Installé. Ensuite :"
echo "  1. nano .env                      -> DEEPSEEK_API_KEY"
echo "  2. python -m chesscoach.cli.update --username <pseudo> --limit 20"
echo "  3. python -m chesscoach.puzzles.lichess --min-rating 600 --max-rating 1400 --limit-per-tag 300"
echo "  4. python -m chesscoach.cli.serve --username <pseudo>   -> http://127.0.0.1:8765/"
echo "Pour l'icône sur l'écran d'accueil : Chrome -> menu -> « Ajouter à l'écran d'accueil »."
