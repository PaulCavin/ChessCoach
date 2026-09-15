"""Explicateur : faits -> prompt versionné -> LLM -> critique. ``python -m chesscoach.agents.explainer --game 1287 --ply 55``"""

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
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="data/chesscoach.sqlite")
    p.add_argument("--game", type=int, required=True, help="numéro chronologique de la partie")
    p.add_argument("--ply", type=int, required=True)
    p.add_argument("--username", default=None)
    args = p.parse_args(argv)
    conn = db.connect(args.db)
    q = "SELECT id FROM games WHERE game_number = ?" + (" AND username = ?" if args.username else "")
    row = conn.execute(q, (args.game, args.username) if args.username else (args.game,)).fetchone()
    mf = build_facts(conn, row["id"], args.ply)
    print("FAITS :\n" + mf.as_prompt_text() + "\n")
    raw, verdict = explain(mf, chat_factory())
    print("BROUILLON LLM :\n" + raw + "\n")
    print("CRITIQUE :", "accepté" if verdict.accepted else "rejeté -> abstention")
    for r in verdict.rejected:
        print("  -", r)
    print("\nEXPLICATION FINALE :\n" + verdict.explanation)
    return 0


if __name__ == "__main__":
    sys.exit(main())
