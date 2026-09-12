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

**Calibration du seuil (échantillon : 50 parties rapid 10|0 les plus récentes,
profondeur 14).** Perte moyenne par coup de l'utilisateur : 77 cp (médiane 19).
Coups de l'utilisateur ≥ seuil, par partie :

| seuil | coups/partie | parties sans aucun | parties avec ≥ 4 |
|---|---|---|---|
| 100 cp | 5,9 | 2 / 50 | 33 |
| **150 cp** | **4,0** | **4 / 50** | **22** |
| 200 cp | 2,8 | 7 / 50 | 15 |
| 300 cp | 1,8 | 15 / 50 | 6 |

150 cp retenu : ≈ 2 à 4 moments par partie après plafonnement, presque aucune
partie vide. À re-vérifier quand le niveau monte (le seuil devra baisser).

---

## D-006 — Règles de classification déterministes et table `critical_moments` (2026-09-12, adoptée, à valider)

**Contexte.** Le diagnostic doit ranger chaque moment critique dans la
taxonomie D-001 sans LLM. Il faut des règles vérifiables, ordonnées, et une
table requêtable pour le rapport et les phases 2-3.

**Choix.** `chesscoach/taxonomy/classify.py` : une fonction par tag, entrée =
position avant le coup, coup joué, éval avant/après, meilleure réponse adverse
(tirée de `evals`), horloge. **La première règle qui s'applique gagne**, dans
cet ordre :

| # | Tag | Règle (python-chess + évals) |
|---|---|---|
| 1 | `missed_mate` | mat forcé pour l'utilisateur avant le coup, plus après |
| 2 | `hanging_piece` | la meilleure réponse adverse capture une pièce (hors pion) non défendue ou par une pièce de moindre valeur, et cette capture **n'existait pas** avant le coup (coup nul) ; exclu si le coup joué était une capture sur la même case (échange) |
| 3 | `ignored_threat` | même capture gagnante, mais elle **existait déjà** avant le coup |
| 4 | `unnecessary_exchange` | coup = capture, reprise adverse sur la même case, pièce prise de valeur ≤ pièce donnée |
| 5 | `king_safety` | la meilleure réponse est un échec **sans capture**, ou le coup avance un pion du bouclier (colonne du roi ± 1) alors que le roque n'est plus possible |
| 6 | `endgame_technique` | matériel hors pions ≤ 13 points pour les deux camps (toute erreur en finale non tactique) |
| 7 | `opening_principle` | ply < 20, le meilleur coup développe (pièce depuis sa rangée initiale ou roque) et pas le coup joué |
| 8 | `passive_piece` | aucune capture ni échec dans le coup joué, le meilleur coup ou la réponse ; le meilleur coup avance une pièce, le coup joué est un pion ou un recul |
| 9 | `calculation_error` | tout le reste |
| + | `time_pressure` | **tag secondaire**, ajouté quand l'horloge < 60 s après le coup |

Points à valider :
- **Un tag principal + `time_pressure` en secondaire** plutôt qu'un tag unique :
  la zeitnot est orthogonale au type d'erreur. Stocké `tags = "primaire,time_pressure"`.
- `calculation_error` en finale est impossible par construction (règle 6 prime)
  : « technique de finale » = « erreur en finale sans motif tactique clair ».
- Phase de la partie : ouverture si ply < 20, finale selon la règle 6, milieu sinon.

Premier passage sur 437 parties rapid 10|0 : calculation_error 40 %,
king_safety 17 %, ignored_threat 13 %, hanging_piece 8 %, unnecessary_exchange
7 %, endgame_technique 6 %, missed_mate 4 %, opening_principle 2 %,
passive_piece 2 %. La règle `king_safety` initiale (tout échec, tout pion
devant un roi non roqué) sortait 28 % : resserrée après lecture de 10 cas.

**Raison.** Des règles lisibles et falsifiables : chaque tag peut être
contesté position par position, et un désaccord devient un cas du jeu
d'évaluation. `passive_piece` et `calculation_error` restent les plus faibles ;
à revoir avec les cas réels de phase 2.

Table `critical_moments` (schéma v3) : dérivée, effacée et recalculée à chaque
`python -m chesscoach.taxonomy.classify_games`.

---

## D-007 — Module `report/` (2026-09-12, adoptée)

Ajout au squelette cible : `chesscoach/report/` (agrégation pure + rendu
Markdown). Le rapport de phase 1 n'a pas sa place dans `cli/` (point d'entrée
de session, phase 2) ni dans `taxonomy/`. Sortie : `reports/<username>.md`
(hors git). Sections : phase, type d'erreur (avec les 3 pires positions par
type, FEN + lien), horloge, ouvertures, évolution mensuelle. Aucune phrase
d'interprétation : des chiffres et des positions.
