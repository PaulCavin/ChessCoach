# Journal des décisions de conception

Toute décision de conception est écrite ici le jour même : contexte, options,
choix, raison. Une décision non écrite est perdue.

Format : `D-NNN — titre` · date · statut (`figée`, `adoptée`, `à valider`).

---

## D-001 — Taxonomie d'erreurs (2026-09-12, figée)

**Contexte.** Le diagnostic (étape 4 de la boucle) classe chaque écart entre le
plan déclaré et le verdict moteur dans une catégorie fixe. Cette catégorie est
la clé de tout le reste : mémoire d'apprenant, sélection de puzzles, rappel
espacé FSRS, courbe de progression. Elle doit donc être stable dès la phase 0.

**Options.**
1. Taxonomie libre, produite par le LLM au cas par cas — rejetée : non
   comparable dans le temps, et contraire au principe « le LLM formule, il ne
   juge jamais ».
2. Thèmes Lichess tels quels (~60 thèmes) — rejetée : trop fins pour un joueur
   ~900 Elo, et beaucoup ne sont pas des *erreurs* mais des motifs tactiques.
3. Dix tags fixes, alignés sur les thèmes Lichess pour la sélection de puzzles —
   **retenue**.

**Choix.** Dix tags, figés, en anglais (identifiants) :

| Tag | Sens (règle déterministe visée en phase 1) | Thèmes Lichess associés |
|---|---|---|
| `hanging_piece` | pièce laissée en prise ou capture gratuite manquée | hangingPiece |
| `missed_mate` | mat forcé disponible non joué | mate, mateIn1/2/3 |
| `ignored_threat` | menace adverse d'un coup non parée | defensiveMove |
| `unnecessary_exchange` | échange qui dégrade l'éval sans gain | exchange |
| `king_safety` | roi exposé, roque manqué ou affaibli | kingsideAttack, queensideAttack, exposedKing |
| `passive_piece` | pièce non développée ou hors jeu, éval qui glisse | trappedPiece |
| `opening_principle` | erreur dans les 10 premiers coups (centre, développement) | opening |
| `endgame_technique` | erreur en finale (≤ 7 pièces hors pions ou sans dames) | endgame, pawnEndgame, rookEndgame |
| `calculation_error` | chute d'éval tactique non couverte par un autre tag | crushing, advantage |
| `time_pressure` | erreur avec < 60 s à l'horloge (et cadence 10 min) | — (position rejouée) |

Implémentation : `chesscoach/taxonomy/tags.py` (`Tag`, `TAGS`, `LICHESS_THEMES`).
Le test `tests/test_taxonomy.py` échoue si la liste change.

**Raison.** Assez grossier pour être robuste avec Stockfish + règles simples,
assez fin pour piloter des exercices ciblés. **Ajouter ou renommer un tag est
une nouvelle décision** dans ce journal ; les valeurs sont stockées telles
quelles en SQLite et dans la mémoire d'apprenant, donc jamais renommées.

---

## D-002 — Schéma SQLite : brut d'abord, dérivé ensuite (2026-09-12, à valider)

**Contexte.** Phase 0 exige 100+ parties requêtables en SQL. Les phases 1-3
ajouteront évals, moments critiques, tags, sessions.

**Options.**
1. Une table `games` avec le PGN brut seulement — trop pauvre pour requêter
   par coup/horloge sans re-parser.
2. Tables `games` + `moves` avec FEN calculée par python-chess à l'ingestion —
   couple l'ingestion à la légalité des coups et à une dépendance lourde.
3. `games` (métadonnées API + PGN brut, source de vérité) + `moves` (ply, SAN,
   horloge) + `archive_months` (idempotence) ; **les FEN et évals sont
   calculées en phase 1 dans des tables séparées** à partir du PGN stocké —
   **retenue**.

**Choix.** Voir `chesscoach/db.py` (`SCHEMA`, `schema_version = 1`).
Points notables :
- `games.id` = URL Chess.com de la partie (stable, unique).
- `user_color` / `user_result` dénormalisés pour que le rapport de phase 1
  soit une requête SQL simple.
- `moves.clock_seconds` = temps restant *après* le coup (`[%clk]`), en
  secondes flottantes, NULL si absent.
- `archive_months` mémorise les mois téléchargés ; le mois courant est
  retéléchargé à chaque exécution (parties nouvelles), les autres jamais.

**Raison.** Ré-analyser (nouveau Stockfish, nouvelle profondeur) ne doit jamais
exiger de re-télécharger. Séparer brut et dérivé garde `ingest/` testable sans
moteur ni python-chess.

**À valider par l'utilisateur** (le brief demande une question avant toute
décision engageant le schéma) : le nommage et la dénormalisation ci-dessus.
Changement = migration + incrément de `SCHEMA_VERSION`.

---

## D-003 — Parseur PGN maison pour l'ingestion (2026-09-12, adoptée)

**Contexte.** L'ingestion doit extraire en-têtes, coups SAN et horloges des PGN
Chess.com. python-chess sait le faire, mais valide aussi la légalité, ce qui
n'apporte rien au stockage brut et fait échouer l'ingestion sur un PGN exotique
(variantes, parties abandonnées).

**Choix.** `chesscoach/ingest/pgn.py` : tokenizer regex sans dépendance
(en-têtes, commentaires `{[%clk …]}`, variantes ignorées, NAG ignorés, résultat).
Aucune vérification de légalité. python-chess reste la seule référence pour
tout fait sur une position (FEN, coups légaux, pièces pendues) à partir de la
phase 1.

**Raison.** Ingestion robuste et testable hors ligne ; la légalité et les FEN
sont recalculées d'un bloc en phase 1 depuis `games.pgn`. Contrainte
pratique du jour : PyPI inaccessible depuis l'environnement de développement,
donc la phase 0 devait tourner sans dépendance tierce.

---

## D-004 — Client Chess.com : urllib + injection du fetcher (2026-09-12, adoptée)

**Choix.** `chesscoach/ingest/chesscom.py` utilise `urllib.request` (aucune
dépendance), un `User-Agent` explicite (obligatoire, sinon 403), retries avec
backoff sur 429/5xx. Toutes les fonctions acceptent un paramètre `fetch`
(callable `url -> dict`) pour être testées sans réseau à partir du PGN de
`tests/fixtures/sample_chesscom.pgn`.

**Raison.** Chaque module doit être utilisable seul et testable sans LLM ni
réseau ; l'API Chess.com est publique et sans clé, `requests` n'apporte rien.

---

## Question ouverte

- Version de Python : le brief vise 3.12 ; l'environnement de développement du
  jour est en 3.11, `pyproject.toml` déclare donc `>=3.11`. Aucun code ne
  dépend de 3.12.

---

## Phase 0 — critère de sortie atteint (2026-09-12)

Ingestion complète de `Kuga06` : **1285 parties** (2018-12 → 2026-09), 70 881
coups, 11 horloges manquantes seulement, 0 désaccord entre le parseur maison et
python-chess sur les 1285 PGN rejoués. Base locale `data/chesscoach.sqlite`
(hors git).

Faits utiles pour la phase 1 :
- Cadences : rapid 10|0 = 597 parties, rapid 15|10 = 314, blitz 5|0 = 100,
  daily = 51. Le rapport ciblera **rapid 10|0 par défaut** (cadence du brief).
- Elo rapid depuis 2025-08 : 710–902, moyenne 786.
- 602 victoires / 657 défaites / 26 nulles ; mêmes proportions blancs et noirs.
- 268 parties où l'utilisateur descend sous 60 s : `time_pressure` aura de la
  matière.
- Un adversaire récurrent (`croustijon`, ~100 parties) : à surveiller pour ne
  pas biaiser les statistiques d'ouverture.

---

## D-005 — Oracle moteur : éval par position, table `evals`, seuils (2026-09-12, adoptée)

**Contexte.** Phase 1 : chaque fait sur une position doit venir de Stockfish.
Il faut une éval par coup, stockée, réutilisable par le rapport (phase 1), la
sélection des moments critiques (phase 2) et le croisement avec les puzzles
(phase 3).

**Options.**
1. Analyser à la volée en session — rejetée : 70 coups × 0,2 s à chaque
   ouverture de partie, et impossible d'agréger sur 600 parties.
2. Stocker seulement les moments critiques — rejetée : un changement de seuil
   obligerait à tout recalculer.
3. **Une ligne par position dans `evals`** (schéma v2, additif), les pertes et
   moments critiques recalculés en pur Python (`engine/analysis.py`) — retenue.

**Choix.**
- Stockfish 17.1, binaire dans `bin/` (hors git) ou `$CHESSCOACH_STOCKFISH`,
  1 thread / 64 Mo par processus, N processus = N parties en parallèle.
- **Profondeur fixe 14** (≈ 0,1–0,4 s/position). Reproductible, contrairement
  à une limite en temps.
- `evals(game_id, ply)` = position *avant* le coup `ply` ; `ply_count + 1`
  lignes par partie. Score du point de vue des blancs : `score_cp` ou
  `mate_in` (signé), `mate_in = 0` pour une position finale matée.
- Mats bornés à **±1000 cp** pour les calculs de perte (convention Lichess).
- Perte d'un coup = éval avant − éval après, du point de vue du joueur,
  bornée à 0. Seuils : inexactitude 50, erreur 100, gaffe 300 (Lichess) ;
  **moment critique = perte ≥ 150 cp**, au plus 4 par partie, triés par perte.
  Le seuil 150 est une hypothèse à calibrer sur l'échantillon (voir ci-dessous).
- `analysed_games` trace moteur + profondeur : relancer n'analyse que les
  parties manquantes ; changer de profondeur = vider cette table.
- Migration de schéma : additive uniquement (`CREATE IF NOT EXISTS`), la
  version en base est relevée automatiquement. Une migration destructive
  sera une décision explicite.

**Raison.** Séparer stockage brut (positions évaluées) et interprétation
(seuils, moments) permet de recalibrer sans relancer le moteur ; la
profondeur fixe rend l'oracle déterministe, condition du jeu d'évaluation.
