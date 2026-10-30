# ChessCoach

**Un coach d'échecs personnel, local et gratuit, construit sur vos propres parties.**

ChessCoach télécharge vos parties Chess.com, les fait analyser par Stockfish, repère les
moments où la partie a basculé, les classe dans une taxonomie fixe de dix types d'erreurs,
puis vous les fait **rejouer avant de vous donner le verdict**. Ce que vous ratez revient en
exercices (la position rejouée, des puzzles Lichess du même thème) et en rappels espacés,
jusqu'à ce que le motif disparaisse de vos vraies parties.

Conçu pour un joueur de club ou de loisir (~900 Elo, cadence 10 min), mais rien n'est
spécifique à ce niveau.

## Le principe non négociable

**Le modèle de langage formule, il ne juge jamais.** Toute affirmation sur une position —
évaluation, meilleur coup, pièce en prise, échec, menace — vient de Stockfish ou d'un calcul
python-chess. Le LLM ne reçoit jamais l'échiquier : seulement une liste de faits déjà
vérifiés, qu'il doit reformuler en français. Un critique **écrit en code** rejette toute phrase
qui n'est pas rattachée à un fait, cite un coup non fourni ou emploie un jugement de style
(« passif », « évident »…). Si le texte ne passe pas, le coach dit « voici la ligne, je ne sais
pas mieux l'expliquer » plutôt que d'inventer.

Conséquence pratique : **le coach fonctionne intégralement sans LLM**. Le modèle n'ajoute que
la fluidité de la prose.

## Ce que fait une session (15 minutes, une partie)

1. **Sélection** — Stockfish (profondeur 14) évalue chaque position ; les coups qui perdent au
   moins un pion d'avantage sont retenus, les 4 pires par partie.
2. **Raisonnement d'abord** — la position s'affiche sans verdict. Vous notez votre plan, votre
   confiance (0-100), et vous jouez votre coup sur l'échiquier.
3. **Verdict** — « ton coup mène à X, le meilleur coup mène à Y », X et Y tirés des lignes
   moteur, texte vérifié par le critique.
4. **Diagnostic** — le type d'erreur (pièce pendue, menace ignorée, sécurité du roi…) et votre
   réponse sont écrits dans votre mémoire d'apprenant.
5. **Exercice immédiat** — rejouer la partie deux coups avant, ou un puzzle Lichess du même thème.
6. **Rappel espacé** — un planificateur FSRS révise chaque type d'erreur ; un type est considéré
   acquis quand votre réussite dépasse 80 % **et** que le motif recule dans vos parties réelles.

## Installation

Prérequis : **Python 3.11 ou plus récent** (Stockfish est téléchargé par le script). Vérifiez avec
`python3 --version` ; sur macOS le Python fourni avec Xcode est trop ancien — installez-en un via
[Homebrew](https://brew.sh) (`brew install python@3.12`) ou python.org, puis utilisez `python3.12`
dans les commandes ci-dessous. Sous zsh (macOS), ne collez pas les commentaires `# …` de fin de ligne.

```bash
git clone https://github.com/PaulCavin/ChessCoach && cd ChessCoach
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
sh scripts/install_stockfish.sh            # Stockfish 17.1 : Linux, macOS (Intel/Apple Silicon), Termux
cp .env.example .env                        # clé d'API du LLM (facultatif, fichier ignoré par git)
```

### Sur un téléphone Android (Termux)

Le coach tourne entièrement sur le téléphone, sans serveur distant.

```bash
pkg install -y git && git clone https://github.com/PaulCavin/ChessCoach && cd ChessCoach
sh scripts/install_termux.sh
```

Puis les commandes ci-dessous ; dans Chrome, « Ajouter à l'écran d'accueil » installe la page
comme une appli. Comptez ~1 min d'analyse par partie sur ARM : commencez par `update --limit 20`.
Termux doit rester ouvert pendant la session (notification → « Acquire wakelock »).

## Utilisation

```bash
python -m chesscoach.cli.update --username <pseudo>   # parties, analyse, classification, bilans
python -m chesscoach.cli.serve  --username <pseudo>   # http://127.0.0.1:8765/
```

`update` ne refait que ce qui manque : relancez-la après chaque partie. `serve` n'écoute que sur
votre machine (`127.0.0.1`). Les pages :

| Page | Contenu |
|---|---|
| `/` | vos dernières parties analysées |
| `/game/<n>` | bilan interactif : échiquier jouable, courbe d'éval, moments critiques, mode « à toi de jouer », exercice |
| `/puzzle` | puzzles Lichess du type d'erreur le plus en retard, résolus dans l'échiquier |
| `/progress` | courbe hebdomadaire de chaque type d'erreur dans vos parties réelles, état FSRS |

Autres commandes utiles :

```bash
python -m chesscoach.puzzles.lichess --min-rating 600 --max-rating 1400 --limit-per-tag 400
                                                   # base Lichess CC0, filtrée en flux (~2 500 puzzles, 1 Mo)
python -m chesscoach.cli.review   --username <pseudo>   # plan de révision du jour (FSRS)
python -m chesscoach.report       --username <pseudo> --time-class rapid --time-control 600
                                                   # rapport agrégé Markdown, sans LLM
python -m chesscoach.agents.explainer                 # explications LLM + critique, dernière partie
```

### Le LLM (facultatif)

Par défaut DeepSeek via API ; Ollama (local) et Anthropic sont supportés. Configuration dans
`.env` : `CHESSCOACH_LLM_PROVIDER` (`deepseek` | `ollama` | `anthropic`), `CHESSCOACH_LLM_MODEL`,
et la clé correspondante. Seule la liste de faits (évaluations, coups) est envoyée à l'API —
jamais le PGN complet ni des données personnelles.

## Votre mémoire d'apprenant

`memory/learner/` contient des fichiers Markdown à frontmatter YAML, lisibles dans Obsidian ou
n'importe quel éditeur : une note par type d'erreur (occurrences, réussite, état FSRS, prochaine
révision), une note par session, un profil. Chaque fichier se termine par une section `## Notes`
qui **vous appartient** : le programme la relit et ne la réécrit jamais. Les données de
référence sont dans SQLite (`data/chesscoach.sqlite`, un seul fichier à sauvegarder).

## La taxonomie

Dix types d'erreurs, figés, alignés sur les thèmes de puzzles Lichess :
`hanging_piece`, `missed_mate`, `ignored_threat`, `unnecessary_exchange`, `king_safety`,
`passive_piece`, `opening_principle`, `endgame_technique`, `calculation_error`, `time_pressure`.
Chaque type est attribué par une règle python-chess vérifiable position par position
(`chesscoach/taxonomy/classify.py`) ; ajouter ou renommer un type est une décision documentée.

## Architecture

```
chesscoach/
  ingest/      API Chess.com → SQLite (parties, coups, horloges)
  engine/      Stockfish, éval par position, moments critiques
  taxonomy/    les 10 types d'erreurs et leurs règles déterministes
  agents/      faits → prompt versionné → LLM → critique (code)
  memory/      mémoire d'apprenant Markdown, FSRS, sortie d'un type
  puzzles/     import Lichess filtré, sélection par type
  report/      rapport Markdown, bilans HTML, échiquier interactif, progression
  eval/        jeu d'évaluation : affirmations à accepter / rejeter
  cli/         update, serve, review
docs/decisions.md   journal de toutes les décisions de conception (contexte, options, choix, raison)
```

Chaque module est utilisable seul et testé sans LLM, sans réseau et (sauf un test) sans Stockfish :

```bash
pytest
```

## État du projet

Les phases 0 à 3 du plan (corpus, analyse, boucle, exercices) sont implémentées et tournent
en local. La phase 4 — une application tout côté client (Stockfish WASM) — attend d'abord
plusieurs mois d'usage réel de la boucle. Historique et raisons dans `docs/decisions.md`.

## Crédits et licence

[Stockfish](https://stockfishchess.org) (GPL v3, binaire téléchargé séparément),
[python-chess](https://python-chess.readthedocs.io) (GPL v3),
[base de puzzles Lichess](https://database.lichess.org/#puzzles) (CC0),
[API publique Chess.com](https://www.chess.com/news/view/published-data-api).
Planificateur [FSRS](https://github.com/open-spaced-repetition/fsrs4anki/wiki) réimplémenté.

Code sous licence MIT — voir `LICENSE`.
