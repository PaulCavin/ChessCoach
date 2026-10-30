from __future__ import annotations

import json

from chesscoach.agents.critic import review
from chesscoach.agents.explainer import explain
from chesscoach.agents.facts import Fact, MomentFacts


def mf():
    m = MomentFacts(1287, 55, "white", "7r/6pp/5pk1/1p3Q2/4PPn1/7q/PP2K2P/R6R w - - 0 27", "Rac1", "Qd5")
    m.facts = [
        Fact("eval_before", "Éval avant ton coup : +2.36 pour toi."),
        Fact("eval_after", "Éval après ton coup Rac1 : mat en 3 pour les noirs."),
        Fact("best_move", "Meilleur coup selon Stockfish : Qd5."),
    ]
    m.best_line_san = "28.Qd5 Kg6 29.Rg1"
    return m


def test_critic_accepts_fully_grounded_explanation():
    raw = json.dumps(
        {
            "explanation": "Avant Rac1 tu étais à +2.36. Rac1 mène à un mat en 3 pour les noirs. Le meilleur coup était Qd5.",
            "claims": [
                {"text": "Avant Rac1 tu étais à +2.36", "fact": "eval_before"},
                {"text": "Rac1 mène à un mat en 3", "fact": "eval_after"},
                {"text": "Le meilleur coup était Qd5", "fact": "best_move"},
            ],
        }
    )
    v = review(raw, mf())
    assert v.accepted and v.rejected == []


def test_critic_rejects_style_words_unlisted_moves_and_unbacked_sentences():
    raw = json.dumps(
        {
            "explanation": "Rac1 est un coup passif. Qd5+ met le roi en échec. La dame f5 défend e2.",
            "claims": [
                {"text": "Rac1 est un coup passif", "fact": "eval_after"},
                {"text": "Qd5+ met le roi en échec", "fact": "gives_check"},
            ],
        }
    )
    v = review(raw, mf())
    assert not v.accepted
    joined = " | ".join(v.rejected)
    assert "passif" in joined and "fait inconnu" in joined and "phrase sans fait" in joined
    assert "Je ne sais pas mieux l'expliquer" in v.explanation and "28.Qd5" in v.explanation


def test_critic_abstains_on_unparseable_output():
    v = review("désolé, je ne peux pas", mf())
    assert not v.accepted and v.rejected == ["réponse LLM illisible"]


def test_explain_uses_prompt_and_fake_llm():
    seen = {}

    def fake(messages):
        seen["system"] = messages[0]["content"]
        return json.dumps(
            {
                "explanation": "Le meilleur coup était Qd5.",
                "claims": [{"text": "Le meilleur coup était Qd5", "fact": "best_move"}],
            }
        )

    raw, v = explain(mf(), fake)
    assert "[best_move]" in seen["system"] and "RÈGLE ABSOLUE" in seen["system"]
    assert v.accepted
