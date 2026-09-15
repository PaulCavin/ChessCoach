"""Schéma SQLite et connexion (décision D-002).

Principe : la base stocke les données brutes (PGN complet, coups, horloges).
Tout ce qui est dérivé (FEN, éval, moments critiques) est ajouté par les phases
suivantes dans des tables séparées, pour pouvoir ré-analyser sans re-télécharger.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 6
MIN_COMPATIBLE_VERSION = 4  # v4 a changé la clé des parties : base < 4 -> supprimer et ré-ingérer

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER NOT NULL
);

-- Une ligne par partie (D-002 révisée).
CREATE TABLE IF NOT EXISTS games (
    id              INTEGER PRIMARY KEY,        -- clé interne
    url             TEXT NOT NULL UNIQUE,       -- lien de la partie sur Chess.com (information)
    game_number     INTEGER,                    -- n° chronologique de la partie pour ce compte (1 = première jouée)
    username        TEXT NOT NULL,              -- compte ingéré (l'apprenant)
    user_color      TEXT NOT NULL CHECK (user_color IN ('white', 'black')),
    white           TEXT NOT NULL,
    black           TEXT NOT NULL,
    white_elo       INTEGER,
    black_elo       INTEGER,
    result          TEXT NOT NULL,              -- '1-0', '0-1', '1/2-1/2', '*'
    user_result     TEXT NOT NULL CHECK (user_result IN ('win', 'loss', 'draw', 'unknown')),
    termination     TEXT,                       -- en-tête PGN Termination
    time_control    TEXT,                       -- ex. '600' ou '600+5'
    time_class      TEXT,                       -- bullet / blitz / rapid / daily
    rated           INTEGER,                    -- 0/1
    rules           TEXT,                       -- 'chess', 'chess960', ...
    eco             TEXT,
    eco_url         TEXT,
    end_time        INTEGER,                    -- epoch UTC (API Chess.com)
    played_at       TEXT,                       -- ISO 8601 UTC dérivé de end_time
    ply_count       INTEGER NOT NULL,
    pgn             TEXT NOT NULL,              -- PGN brut, source de vérité
    ingested_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_games_user_time ON games (username, end_time);
CREATE UNIQUE INDEX IF NOT EXISTS idx_games_user_number ON games (username, game_number);
CREATE INDEX IF NOT EXISTS idx_games_time_class ON games (time_class);

-- Un coup par ligne. ply 1 = premier coup blanc.
CREATE TABLE IF NOT EXISTS moves (
    game_id         INTEGER NOT NULL REFERENCES games (id) ON DELETE CASCADE,
    ply             INTEGER NOT NULL,
    move_number     INTEGER NOT NULL,           -- numéro affiché dans le PGN
    color           TEXT NOT NULL CHECK (color IN ('white', 'black')),
    san             TEXT NOT NULL,
    clock_seconds   REAL,                       -- temps restant après le coup ([%clk])
    PRIMARY KEY (game_id, ply)
);

-- Mois d'archive déjà téléchargés : rend l'ingestion idempotente.
CREATE TABLE IF NOT EXISTS archive_months (
    username        TEXT NOT NULL,
    year            INTEGER NOT NULL,
    month           INTEGER NOT NULL,
    game_count      INTEGER NOT NULL,
    fetched_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (username, year, month)
);

-- Phase 1 (D-005). Une ligne par position *avant* chaque coup joué (ply = coup à venir),
-- plus une ligne ply = ply_count + 1 pour la position finale. Scores du point de vue des blancs.
CREATE TABLE IF NOT EXISTS evals (
    game_id         INTEGER NOT NULL REFERENCES games (id) ON DELETE CASCADE,
    ply             INTEGER NOT NULL,
    fen             TEXT NOT NULL,
    score_cp        INTEGER,                    -- centipions, NULL si mat annoncé
    mate_in         INTEGER,                    -- +n : blancs matent en n ; -n : noirs
    best_move       TEXT,                       -- UCI, NULL en position terminale
    best_pv         TEXT,                       -- UCI séparés par des espaces
    depth           INTEGER NOT NULL,
    PRIMARY KEY (game_id, ply)
);

-- Parties déjà analysées (idempotence + traçabilité moteur/profondeur).
CREATE TABLE IF NOT EXISTS analysed_games (
    game_id         INTEGER PRIMARY KEY REFERENCES games (id) ON DELETE CASCADE,
    engine          TEXT NOT NULL,
    depth           INTEGER NOT NULL,
    analysed_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Phase 1 (D-006). Moments critiques de l'utilisateur, classés. Dérivé de evals + moves :
-- recalculable à tout moment (python -m chesscoach.taxonomy.classify_games).
CREATE TABLE IF NOT EXISTS critical_moments (
    game_id         INTEGER NOT NULL REFERENCES games (id) ON DELETE CASCADE,
    ply             INTEGER NOT NULL,           -- coup joué par l'utilisateur
    rank            INTEGER NOT NULL,           -- 1 = plus grosse perte de la partie
    san             TEXT NOT NULL,
    fen_before      TEXT NOT NULL,
    best_move       TEXT,                       -- UCI
    before_cp       INTEGER NOT NULL,           -- point de vue de l'utilisateur
    after_cp        INTEGER NOT NULL,
    loss            INTEGER NOT NULL,
    severity        TEXT NOT NULL,              -- inaccuracy / mistake / blunder
    phase           TEXT NOT NULL CHECK (phase IN ('opening', 'middlegame', 'endgame')),
    clock_seconds   REAL,
    primary_tag     TEXT NOT NULL,
    tags            TEXT NOT NULL,              -- tags séparés par des virgules (primaire en premier)
    PRIMARY KEY (game_id, ply)
);
CREATE INDEX IF NOT EXISTS idx_cm_tag ON critical_moments (primary_tag);

-- Phase 2 (D-011). Réponses de l'apprenant, enregistrées AVANT toute révélation (raisonnement d'abord).
-- Source de vérité de la mémoire d'apprenant ; les fichiers Markdown sont générés à partir d'ici.
CREATE TABLE IF NOT EXISTS learner_events (
    id              INTEGER PRIMARY KEY,
    ts              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    username        TEXT NOT NULL,
    game_id         INTEGER NOT NULL REFERENCES games (id) ON DELETE CASCADE,
    ply             INTEGER NOT NULL,
    primary_tag     TEXT NOT NULL,
    tags            TEXT NOT NULL,
    user_move       TEXT NOT NULL,              -- SAN du coup essayé
    plan            TEXT,                       -- plan déclaré (texte libre)
    confidence      INTEGER,                    -- 0-100 déclaré avant révélation
    verdict         TEXT NOT NULL CHECK (verdict IN ('best', 'played', 'other')),
    loss            INTEGER NOT NULL,           -- perte du coup joué en partie (cp)
    kind            TEXT NOT NULL DEFAULT 'answer' CHECK (kind IN ('answer', 'exercise'))
);
CREATE INDEX IF NOT EXISTS idx_le_user_tag ON learner_events (username, primary_tag, ts);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    """Ouvre (et initialise si besoin) la base. ``":memory:"`` accepté pour les tests."""
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    has_version = conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'schema_version'").fetchone()
    row = conn.execute("SELECT version FROM schema_version").fetchone() if has_version else None
    if row is not None and row["version"] < MIN_COMPATIBLE_VERSION:
        raise RuntimeError(
            f"Base en version {row['version']}, incompatible (minimum {MIN_COMPATIBLE_VERSION}) : "
            "supprimer le fichier et relancer l'ingestion (python -m chesscoach.ingest.chesscom <username>)."
        )
    conn.executescript(SCHEMA)
    _migrate_columns(conn)
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
    elif row["version"] < SCHEMA_VERSION:
        # Les versions successives sont additives (CREATE IF NOT EXISTS) : le script ci-dessus vient de
        # créer les tables manquantes. Une migration destructive devra être explicite.
        conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
    elif row["version"] > SCHEMA_VERSION:
        raise RuntimeError(f"Base en version {row['version']}, plus récente que le code ({SCHEMA_VERSION}).")
    conn.commit()


# Colonnes ajoutées après coup : (table, colonne, définition). Idempotent.
ADDED_COLUMNS = (("learner_events", "kind", "TEXT NOT NULL DEFAULT 'answer'"),)


def _migrate_columns(conn: sqlite3.Connection) -> None:
    for table, column, definition in ADDED_COLUMNS:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
