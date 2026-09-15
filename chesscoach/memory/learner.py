"""Enregistrement des réponses de l'apprenant et génération des notes Markdown.

Arborescence (``memory/learner/`` par défaut) :
  profile.md                 frontmatter (pseudo, cadence, Elo) + « ## Notes » (à toi)
  tags/<tag>.md              frontmatter (compteurs) + tableau des occurrences + « ## Notes » (à toi)
  sessions/<date>_g<n>.md    une note par session, générée une fois
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from chesscoach.taxonomy.tags import Tag

NOTES_HEADER = "## Notes"
NOTES_HINT = "_Cette section t'appartient : le programme ne la réécrit jamais._"
TAG_LABEL = {
    "hanging_piece": "Pièce pendue",
    "missed_mate": "Mat manqué",
    "ignored_threat": "Menace ignorée",
    "unnecessary_exchange": "Échange inutile",
    "king_safety": "Sécurité du roi",
    "passive_piece": "Pièce passive",
    "opening_principle": "Principe d'ouverture",
    "endgame_technique": "Technique de finale",
    "calculation_error": "Erreur de calcul",
    "time_pressure": "Zeitnot",
}


@dataclass(frozen=True)
class Answer:
    username: str
    game_id: int
    ply: int
    user_move: str
    plan: str | None
    confidence: int | None
    verdict: str  # best | played | other


def record_answer(conn: sqlite3.Connection, a: Answer) -> int:
    """Insère l'événement (avant toute révélation côté interface). Retourne son id."""
    cm = conn.execute("SELECT * FROM critical_moments WHERE game_id = ? AND ply = ?", (a.game_id, a.ply)).fetchone()
    if cm is None:
        raise ValueError(f"pas de moment critique en ply {a.ply} pour la partie {a.game_id}")
    if a.verdict not in ("best", "played", "other"):
        raise ValueError(f"verdict inconnu : {a.verdict}")
    conf = None if a.confidence is None else max(0, min(100, int(a.confidence)))
    cur = conn.execute(
        "INSERT INTO learner_events (username, game_id, ply, primary_tag, tags, user_move, plan, confidence, verdict, loss)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            a.username,
            a.game_id,
            a.ply,
            cm["primary_tag"],
            cm["tags"],
            a.user_move,
            (a.plan or "").strip() or None,
            conf,
            a.verdict,
            cm["loss"],
        ),
    )
    conn.commit()
    return cur.lastrowid


# --- Markdown ---------------------------------------------------------------


def _read_notes(path: Path) -> str:
    """Récupère la section Notes existante (tout ce qui suit « ## Notes »)."""
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    idx = text.find(NOTES_HEADER)
    if idx < 0:
        return ""
    body = text[idx + len(NOTES_HEADER) :]
    body = body.replace(NOTES_HINT, "", 1)
    return body.strip("\n")


def _write_with_notes(path: Path, generated: str, notes: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tail = f"\n{NOTES_HEADER}\n{NOTES_HINT}\n" + (f"\n{notes}\n" if notes else "\n")
    path.write_text(generated.rstrip("\n") + "\n" + tail, encoding="utf-8")


def _yaml(d: dict) -> str:
    lines = ["---"]
    for k, v in d.items():
        if isinstance(v, list):
            lines.append(f"{k}:")
            lines += [f"  - {x}" for x in v]
        elif v is None:
            lines.append(f"{k}: null")
        elif isinstance(v, str) and re.search(r"[:#\[\]{}]", v):
            lines.append(f'{k}: "{v}"')
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


def write_tag_notes(conn: sqlite3.Connection, username: str, root: Path) -> list[Path]:
    written = []
    for tag in Tag:
        rows = conn.execute(
            """SELECT e.*, g.game_number FROM learner_events e JOIN games g ON g.id = e.game_id
               WHERE e.username = ? AND e.primary_tag = ? ORDER BY e.ts""",
            (username, tag.value),
        ).fetchall()
        path = root / "tags" / f"{tag.value}.md"
        if not rows and not path.exists():
            continue
        n = len(rows)
        best = sum(1 for r in rows if r["verdict"] == "best")
        conf = [r["confidence"] for r in rows if r["confidence"] is not None]
        front = _yaml(
            {
                "tag": tag.value,
                "label": TAG_LABEL[tag.value],
                "occurrences": n,
                "found_best": best,
                "success_rate": round(best / n, 2) if n else None,
                "avg_confidence": round(sum(conf) / len(conf)) if conf else None,
                "last_seen": rows[-1]["ts"][:10] if rows else None,
                "updated": datetime.now(tz=UTC).strftime("%Y-%m-%d"),
            }
        )
        body = [
            front,
            f"# {TAG_LABEL[tag.value]}",
            "",
            "| Date | Partie | Coup | Ton essai | Confiance | Verdict | Plan déclaré |",
            "|---|---|---:|---|---:|---|---|",
        ]
        for r in rows:
            body.append(
                f"| {r['ts'][:10]} | [[sessions/{r['ts'][:10]}_g{r['game_number']}\\|n° {r['game_number']}]] | {(r['ply'] + 1) // 2} "
                f"| {r['user_move']} | {r['confidence'] if r['confidence'] is not None else '—'} | {VERDICT_FR[r['verdict']]} "
                f"| {(r['plan'] or '').replace('|', '/')} |"
            )
        _write_with_notes(path, "\n".join(body), _read_notes(path))
        written.append(path)
    return written


VERDICT_FR = {"best": "✔ meilleur coup", "played": "✖ coup de la partie", "other": "? non évalué"}


def write_session_note(conn: sqlite3.Connection, username: str, game_id: int, root: Path) -> Path:
    g = conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
    rows = conn.execute(
        "SELECT * FROM learner_events WHERE username = ? AND game_id = ? ORDER BY ply, ts", (username, game_id)
    ).fetchall()
    date = (rows[0]["ts"] if rows else datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))[:10]
    path = root / "sessions" / f"{date}_g{g['game_number']}.md"
    front = _yaml(
        {
            "date": date,
            "game_number": g["game_number"],
            "url": g["url"],
            "color": g["user_color"],
            "result": g["user_result"],
            "answers": len(rows),
            "tags": sorted({r["primary_tag"] for r in rows}),
        }
    )
    body = [
        front,
        f"# Session du {date} — partie n° {g['game_number']}",
        "",
        f"{'Blancs' if g['user_color'] == 'white' else 'Noirs'} contre {g['black'] if g['user_color'] == 'white' else g['white']}, "
        f"résultat : {g['user_result']}.",
        "",
    ]
    for r in rows:
        body += [
            f"## Coup {(r['ply'] + 1) // 2} — [[tags/{r['primary_tag']}\\|{TAG_LABEL[r['primary_tag']]}]]",
            f"- Ton essai : **{r['user_move']}** → {VERDICT_FR[r['verdict']]}",
            f"- Confiance déclarée : {r['confidence'] if r['confidence'] is not None else '—'}",
            f"- Plan déclaré : {r['plan'] or '—'}",
            f"- Perte du coup joué en partie : {r['loss']} cp",
            "",
        ]
    _write_with_notes(path, "\n".join(body), _read_notes(path))
    return path


def write_profile(conn: sqlite3.Connection, username: str, root: Path) -> Path:
    g = conn.execute(
        "SELECT * FROM games WHERE username = ? AND rules = 'chess' ORDER BY end_time DESC LIMIT 1", (username,)
    ).fetchone()
    elo = (g["white_elo"] if g["user_color"] == "white" else g["black_elo"]) if g else None
    n_events = conn.execute("SELECT count(*) FROM learner_events WHERE username = ?", (username,)).fetchone()[0]
    path = root / "profile.md"
    front = _yaml(
        {
            "username": username,
            "elo": elo,
            "time_control": g["time_control"] if g else None,
            "games": conn.execute("SELECT count(*) FROM games WHERE username = ?", (username,)).fetchone()[0],
            "answers": n_events,
            "updated": datetime.now(tz=UTC).strftime("%Y-%m-%d"),
        }
    )
    _write_with_notes(path, front + f"\n# {username}\n", _read_notes(path))
    return path


def sync_markdown(conn: sqlite3.Connection, username: str, game_id: int | None, root: Path) -> list[Path]:
    out = [write_profile(conn, username, root), *write_tag_notes(conn, username, root)]
    if game_id is not None:
        out.append(write_session_note(conn, username, game_id, root))
    return out
