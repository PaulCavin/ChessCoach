"""``python -m chesscoach.report --username Kuga06 [--time-class rapid --time-control 600] [--out reports/x.md]``"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from chesscoach import db
from chesscoach.report.aggregate import build_report
from chesscoach.report.render import render


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Rapport agrégé sans LLM.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--db", default="data/chesscoach.sqlite")
    parser.add_argument("--time-class")
    parser.add_argument("--time-control")
    parser.add_argument("--out", help="fichier Markdown de sortie (sinon stdout)")
    args = parser.parse_args(argv)
    report = build_report(
        db.connect(args.db), args.username, time_class=args.time_class, time_control=args.time_control
    )
    text = render(report)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"rapport écrit : {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
