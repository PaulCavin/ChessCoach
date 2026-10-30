"""Critique déterministe (D-008) : ne laisse passer que les phrases rattachées à un fait fourni,
sans mot de jugement interdit ni coup non listé. Aucun LLM ici."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from chesscoach.agents.facts import MomentFacts

FORBIDDEN_WORDS = (
    "passif",
    "passive",
    "naturel",
    "naturelle",
    "évident",
    "évidente",
    "élégant",
    "élégante",
    "logique",
    "prudent",
    "prudente",
    "agressif",
    "agressive",
    "solide",
    "actif",
    "active",
)
_SAN_RE = re.compile(r"\b(?:O-O(?:-O)?|[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?)\b")


@dataclass
class Verdict:
    accepted: bool
    explanation: str
    rejected: list[str] = field(default_factory=list)


def abstention(mf: MomentFacts) -> str:
    """Texte de repli, composé uniquement de faits : utilisé quand le LLM est absent ou rejeté."""
    before = _fact(mf, "eval_before").split(" : ", 1)[-1].rstrip(".")
    after = _fact(mf, "eval_after").split(" : ", 1)[-1].rstrip(".")
    return (
        f"Avant {mf.played_san}, l'éval était {before}. Après {mf.played_san}, elle passe à {after}. "
        f"Le meilleur coup était {mf.best_san} ({mf.best_line_san}). "
        "Je ne sais pas mieux l'expliquer sans risquer d'inventer."
    )


def _fact(mf: MomentFacts, fid: str) -> str:
    return next((f.text for f in mf.facts if f.id == fid), "")


def review(raw: str, mf: MomentFacts) -> Verdict:
    """Parse la réponse JSON du LLM, vérifie chaque phrase ; en cas de doute -> abstention."""
    try:
        data = json.loads(raw[raw.index("{") : raw.rindex("}") + 1])
        explanation = str(data["explanation"]).strip()
        claims = {c["text"].strip(): c["fact"] for c in data.get("claims", [])}
    except (ValueError, KeyError, TypeError, AttributeError):
        return Verdict(False, abstention(mf), ["réponse LLM illisible"])

    fact_ids = {f.id for f in mf.facts}
    allowed_moves = set(_SAN_RE.findall(" ".join(f.text for f in mf.facts)))
    rejected = []
    lower = explanation.lower()
    for w in FORBIDDEN_WORDS:
        if re.search(rf"\b{w}\b", lower):
            rejected.append(f"mot de jugement interdit : {w}")
    for move in set(_SAN_RE.findall(explanation)):
        if move not in allowed_moves and move.rstrip("+#") not in {m.rstrip("+#") for m in allowed_moves}:
            rejected.append(f"coup non fourni par l'oracle : {move}")
    for text, fid in claims.items():
        if fid not in fact_ids:
            rejected.append(f"fait inconnu « {fid} » pour : {text}")
        elif text not in explanation:
            rejected.append(f"affirmation absente du texte : {text}")
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", explanation) if s.strip()]
    for s in sentences:
        if not any(t in s for t in claims):
            rejected.append(f"phrase sans fait : {s}")
    if rejected:
        return Verdict(False, abstention(mf), rejected)
    return Verdict(True, explanation)
