"""Page « Progression par tag » : courbe hebdomadaire du motif dans les parties réelles (oracle),
état FSRS et réussite en exercice. Aucun LLM. C'est la vue du critère de sortie de la phase 3.

``python -m chesscoach.report.progress --username Kuga06 --weeks 8 --out reports/html/progress.html``
"""

from __future__ import annotations

import argparse
import html
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from chesscoach import db
from chesscoach.memory.fsrs import load_card
from chesscoach.memory.progress import rebuild_schedule, tag_progress
from chesscoach.report.html import CSS
from chesscoach.report.render import TAG_LABEL
from chesscoach.taxonomy.tags import Tag

STATE_FR = {"learning": "en cours", "review": "révision", "retired": "acquis", None: "jamais vu"}


@dataclass
class Week:
    start: date
    games: int
    per_tag: dict[str, int]


def weeks(conn: sqlite3.Connection, username: str, n: int, today: date | None = None) -> list[Week]:
    """n dernières semaines (lundi -> dimanche), occurrences par tag dans les parties analysées."""
    today = today or datetime.now(tz=UTC).date()
    monday = today - timedelta(days=today.weekday())
    out = []
    for k in range(n - 1, -1, -1):
        start = monday - timedelta(weeks=k)
        end = start + timedelta(days=7)
        rows = conn.execute(
            """SELECT cm.primary_tag AS tag, count(*) AS n FROM games g JOIN analysed_games a ON a.game_id = g.id
               LEFT JOIN critical_moments cm ON cm.game_id = g.id
               WHERE g.username = ? AND g.played_at >= ? AND g.played_at < ? GROUP BY cm.primary_tag""",
            (username, start.isoformat(), end.isoformat()),
        ).fetchall()
        games = conn.execute(
            """SELECT count(*) FROM games g JOIN analysed_games a ON a.game_id = g.id
               WHERE g.username = ? AND g.played_at >= ? AND g.played_at < ?""",
            (username, start.isoformat(), end.isoformat()),
        ).fetchone()[0]
        out.append(Week(start, games, {r["tag"]: r["n"] for r in rows if r["tag"]}))
    return out


def sparkline(values: list[float | None], width: int = 180, height: int = 34) -> str:
    """Courbe des occurrences par partie ; les semaines sans partie sont des trous (non tracées)."""
    known = [v for v in values if v is not None]
    top = max(known) if known else 1.0
    top = top or 1.0
    n = len(values)
    pts, segments = [], []
    for i, v in enumerate(values):
        if v is None:
            if pts:
                segments.append(pts)
            pts = []
            continue
        x = i / max(1, n - 1) * (width - 4) + 2
        y = height - 4 - (v / top) * (height - 8)
        pts.append(f"{x:.1f},{y:.1f}")
    if pts:
        segments.append(pts)
    lines = "".join(
        f'<polyline points="{" ".join(seg)}" fill="none" stroke="#7fc97f" stroke-width="1.6" stroke-linejoin="round"/>'
        if len(seg) > 1
        else f'<circle cx="{seg[0].split(",")[0]}" cy="{seg[0].split(",")[1]}" r="1.6" fill="#7fc97f"/>'
        for seg in segments
    )
    last = (
        next(
            (
                f'<circle cx="{p.split(",")[0]}" cy="{p.split(",")[1]}" r="2.6" fill="#fff"/>'
                for p in reversed(segments[-1])
            ),
            "",
        )
        if segments
        else ""
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}">'
        f'<line x1="2" y1="{height - 4}" x2="{width - 2}" y2="{height - 4}" stroke="#444" stroke-width=".8"/>'
        f"{lines}{last}</svg>"
    )


def build(conn: sqlite3.Connection, username: str, n_weeks: int = 8, today: date | None = None) -> str:
    rebuild_schedule(conn, username)
    ws = weeks(conn, username, n_weeks, today)
    rows = []
    for tag in Tag:
        prog = tag_progress(conn, username, tag.value)
        card = load_card(conn, username, tag.value)
        series = [(w.per_tag.get(tag.value, 0) / w.games) if w.games else None for w in ws]
        total = sum(w.per_tag.get(tag.value, 0) for w in ws)
        if total == 0 and prog.reviews == 0:
            continue
        trend = "→"
        if prog.recent_per_game is not None and prog.baseline_per_game is not None:
            trend = "↓" if prog.declining else ("↑" if prog.recent_per_game > prog.baseline_per_game else "→")
        rate = f"{prog.success_rate * 100:.0f} %" if prog.success_rate is not None else "—"
        due = card.due.strftime("%Y-%m-%d") if card and card.due else "—"
        rows.append(
            f'<tr><td><b>{TAG_LABEL[tag.value]}</b><div class="ev" style="font-size:.8rem">{tag.value}</div></td>'
            f'<td>{sparkline(series)}</td><td style="text-align:right">{total}</td>'
            f'<td style="text-align:right">{prog.recent_per_game if prog.recent_per_game is not None else "—"}'
            f' <span class="{"good" if trend == "↓" else "bad" if trend == "↑" else ""}">{trend}</span></td>'
            f'<td style="text-align:right">{prog.reviews}</td><td style="text-align:right">{rate}</td>'
            f'<td><span class="chip">{STATE_FR[card.state if card else None]}</span></td>'
            f'<td style="text-align:right">{due}</td></tr>'
        )
    labels = " · ".join(w.start.strftime("%d/%m") for w in ws)
    games_total = sum(w.games for w in ws)
    return f"""<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Progression — {html.escape(username)}</title><style>{CSS}</style><body><div class="wrap">
<div class="top"><h1>Progression par tag · {html.escape(username)}</h1><a href="index.html">← les parties</a></div>
<div class="meta"><span>{n_weeks} dernières semaines</span><span>{games_total} parties analysées sur la période</span><span>semaines : {labels}</span></div>
<div class="card" style="padding:0;overflow:auto;margin-top:12px"><table class="idx">
<tr><th>Tag</th><th>Occurrences / partie ({n_weeks} sem.)</th><th>Total</th><th>20 dernières parties</th><th>Révisions</th><th>Réussite</th><th>État</th><th>Prochaine</th></tr>
{"".join(rows) or '<tr><td colspan="8">Aucune donnée : analyse des parties et sessions à venir.</td></tr>'}
</table></div>
<p class="meta" style="margin-top:12px">La courbe compte les moments critiques du tag <b>par partie jouée</b> (source : Stockfish, pas d'interprétation).
« Réussite » = part de meilleurs coups trouvés en session et en exercice. « Acquis » = réussite ≥ 80 % <b>et</b> motif en recul dans les parties réelles.</p>
</div></body></html>"""


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--username", required=True)
    p.add_argument("--db", default="data/chesscoach.sqlite")
    p.add_argument("--weeks", type=int, default=8)
    p.add_argument("--out", default="reports/html/progress.html")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(db.connect(a.db), a.username, a.weeks), encoding="utf-8")
    print(f"page écrite : {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
