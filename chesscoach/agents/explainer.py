"""Explicateur : faits -> prompt versionné -> LLM -> critique.

``python -m chesscoach.agents.explainer``            tous les moments de la dernière partie analysée
``python -m chesscoach.agents.explainer --game 1287``  une partie précise (``--ply`` pour un seul moment)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from chesscoach import db
from chesscoach.agents.critic import Verdict, review
from chesscoach.agents.facts import MomentFacts, build_facts
from chesscoach.agents.llm import Chat, chat_factory

PROMPT_PATH = Path(__file__).parent / "prompts" / "explainer_v1.md"


def explain(mf: MomentFacts, chat: Chat) -> tuple[str, Verdict]:
    prompt = PROMPT_PATH.read_text(encoding="utf-8").replace("{facts}", mf.as_prompt_text())
    raw = chat(
        [{"role": "system", "content": prompt}, {"role": "user", "content": f"Coup joué : {mf.played_san}. Explique."}]
    )
    return raw, review(raw, mf)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Explique les moments critiques d'une partie (LLM + critique).")
    p.add_argument("--db", default="data/chesscoach.sqlite")
    p.add_argument("--username", default=None)
    p.add_argument("--game", type=int, help="numéro de la partie (défaut : la dernière analysée)")
    p.add_argument("--ply", type=int, help="un seul moment (demi-coup) ; défaut : tous les moments critiques")
    args = p.parse_args(argv)
    conn = db.connect(args.db)
    where, params = ["1 = 1"], []
    if args.username:
        where.append("g.username = ?")
        params.append(args.username)
    if args.game:
        where.append("g.game_number = ?")
        params.append(args.game)
    row = conn.execute(
        f"SELECT g.id, g.game_number FROM games g JOIN analysed_games a ON a.game_id = g.id"
        f" WHERE {' AND '.join(where)} ORDER BY g.end_time DESC LIMIT 1",
        params,
    ).fetchone()
    if row is None:
        print("aucune partie analysée ne correspond", file=sys.stderr)
        return 1
    plies = (
        [args.ply]
        if args.ply
        else [
            r["ply"]
            for r in conn.execute("SELECT ply FROM critical_moments WHERE game_id = ? ORDER BY ply", (row["id"],))
        ]
    )
    if not plies:
        print(f"partie n° {row['game_number']} : aucun moment critique")
        return 0
    chat = chat_factory()
    print(f"Partie n° {row['game_number']} — {len(plies)} moment(s) critique(s)")
    for ply in plies:
        mf = build_facts(conn, row["id"], ply)
        print(
            f"\n{'=' * 70}\nCoup {(ply + 1) // 2}{'.' if ply % 2 else '…'}{mf.played_san}  (meilleur : {mf.best_san})"
        )
        print("\nFAITS :\n" + mf.as_prompt_text())
        raw, verdict = explain(mf, chat)
        print("\nBROUILLON LLM :\n" + raw)
        print("\nCRITIQUE :", "accepté" if verdict.accepted else "rejeté -> abstention")
        for r in verdict.rejected:
            print("  -", r)
        print("\nEXPLICATION FINALE :\n" + verdict.explanation)
    return 0


if __name__ == "__main__":
    sys.exit(main())
