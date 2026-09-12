"""Schéma SQLite et connexion (décision D-002).

Principe : la base stocke les données brutes (PGN complet, coups, horloges).
Tout ce qui est dérivé (FEN, éval, moments critiques) est ajouté par les phases
suivantes dans des tables séparées, pour pouvoir ré-analyser sans re-télécharger.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER NOT NULL
);

-- Une ligne par partie. Clé = URL Chess.com (stable, unique par partie).
CREATE TABLE IF NOT EXISTS games (
    id              TEXT PRIMARY KEY,           -- URL de la partie sur Chess.com
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
CREATE INDEX IF NOT EXISTS idx_games_time_class ON games (time_class);

-- Un coup par ligne. ply 1 = premier coup blanc.
CREATE TABLE IF NOT EXISTS moves (
    game_id         TEXT NOT NULL REFERENCES games (id) ON DELETE CASCADE,
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
    game_id         TEXT NOT NULL REFERENCES games (id) ON DELETE CASCADE,
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
    game_id         TEXT PRIMARY KEY REFERENCES games (id) ON DELETE CASCADE,
    engine          TEXT NOT NULL,
    depth           INTEGER NOT NULL,
    analysed_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
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
    conn.executescript(SCHEMA)
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
    elif row["version"] < SCHEMA_VERSION:
        # Les versions successives sont additives (CREATE IF NOT EXISTS) : le script ci-dessus vient de
        # créer les tables manquantes. Une migration destructive devra être explicite.
        conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
    elif row["version"] > SCHEMA_VERSION:
        raise RuntimeError(f"Base en version {row['version']}, plus récente que le code ({SCHEMA_VERSION}).")
    conn.commit()
