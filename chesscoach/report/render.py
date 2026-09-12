"""Rendu Markdown (français) du rapport agrégé. Aucune interprétation : des chiffres et des positions."""

from __future__ import annotations

from chesscoach.report.aggregate import CLOCK_BUCKETS, PHASES, Report

PHASE_LABEL = {"opening": "Ouverture (≤ 10 coups)", "middlegame": "Milieu de partie", "endgame": "Finale"}
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


def render(r: Report) -> str:
    o = r.overview
    out = [f"# Rapport ChessCoach — {r.username} ({r.filters})", ""]
    out.append(
        f"**{o.games} parties analysées** du {_d(o.first_game)} au {_d(o.last_game)} — "
        f"{o.wins} V / {o.losses} D / {o.draws} N, score {o.score_pct:.0f} %."
    )
    if o.elo_last:
        out.append(f"Elo : {o.elo_min} → {o.elo_max}, dernier {o.elo_last}.")
    out += [
        "",
        "Toutes les évaluations viennent de Stockfish (profondeur fixe). Perte = centipions cédés par coup,",
        "du point de vue du joueur ; gaffe = perte ≥ 300 cp.",
        "",
    ]

    out += [
        "## 1. Où les points se perdent (par phase)",
        "",
        "| Phase | Coups | Perte moyenne / coup | Gaffes | Gaffes / 100 coups |",
        "|---|---:|---:|---:|---:|",
    ]
    for p in PHASES:
        s = r.phases[p]
        out.append(f"| {PHASE_LABEL[p]} | {s.moves} | {s.avg_loss:.0f} cp | {s.blunders} | {s.blunders_per_100:.1f} |")
    out.append("")

    out += [
        f"## 2. Moments critiques par type d'erreur ({r.total_moments} moments, perte ≥ 150 cp, ≤ 4 par partie)",
        "",
        "| Type | Moments | Part | Perte moyenne | Ouverture | Milieu | Finale |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    ranked = sorted(r.tags.items(), key=lambda kv: -kv[1].count)
    for tag, s in ranked:
        if s.count == 0:
            continue
        part = 100 * s.count / r.total_moments if r.total_moments else 0
        out.append(
            f"| {TAG_LABEL[tag]} | {s.count} | {part:.0f} % | {s.total_loss / s.count:.0f} cp | "
            f"{s.by_phase['opening']} | {s.by_phase['middlegame']} | {s.by_phase['endgame']} |"
        )
    tp = 100 * r.time_pressure_moments / r.total_moments if r.total_moments else 0
    out += ["", f"Zeitnot (tag secondaire, horloge < 60 s) : {r.time_pressure_moments} moments ({tp:.0f} %).", ""]

    out += ["### Positions à revoir (les 3 pires par type)", ""]
    for tag, s in ranked:
        if not s.examples:
            continue
        out.append(f"**{TAG_LABEL[tag]}**")
        out.append("")
        for e in s.examples:
            out.append(
                f"- {_d(e.played_at)}, coup {(e.ply + 1) // 2} ({PHASE_LABEL[e.phase].split(' ')[0].lower()}) : "
                f"joué **{e.san}**, meilleur **{e.best_move_san}**, perte {e.loss} cp — "
                f"[partie n° {e.game_number}]({e.url}) · `{e.fen}`"
            )
        out.append("")

    out += [
        "## 3. Horloge",
        "",
        "| Temps restant | Coups | Perte moyenne / coup | Gaffes / 100 coups |",
        "|---|---:|---:|---:|",
    ]
    for label, _, _ in CLOCK_BUCKETS:
        s = r.clock[label]
        out.append(f"| {label} | {s.moves} | {s.avg_loss:.0f} cp | {s.blunders_per_100:.1f} |")
    out.append("")

    out += [
        "## 4. Ouvertures (≥ 5 parties)",
        "",
        "| Ouverture | Couleur | Parties | Score | Perte moyenne en ouverture |",
        "|---|---|---:|---:|---:|",
    ]
    for op in r.openings:
        if op.games < 5:
            continue
        out.append(
            f"| {op.eco} | {'blancs' if op.color == 'white' else 'noirs'} | {op.games} | {op.score_pct:.0f} % | "
            f"{op.avg_opening_loss:.0f} cp |"
        )
    out.append("")

    out += ["## 5. Évolution mensuelle", "", "| Mois | Parties | Perte moyenne / coup |", "|---|---:|---:|"]
    for month, games, avg in r.monthly[-12:]:
        out.append(f"| {month} | {games} | {avg:.0f} cp |")
    out.append("")
    return "\n".join(out)


def _d(iso: str | None) -> str:
    return iso[:10] if iso else "?"
