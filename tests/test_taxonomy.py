from chesscoach.taxonomy import TAGS, Tag
from chesscoach.taxonomy.tags import LICHESS_THEMES

FROZEN = (
    "hanging_piece",
    "missed_mate",
    "ignored_threat",
    "unnecessary_exchange",
    "king_safety",
    "passive_piece",
    "opening_principle",
    "endgame_technique",
    "calculation_error",
    "time_pressure",
)


def test_taxonomy_is_frozen():
    # Tout changement ici doit être une décision documentée dans docs/decisions.md.
    assert tuple(t.value for t in TAGS) == FROZEN


def test_every_tag_has_a_lichess_mapping_entry():
    assert set(LICHESS_THEMES) == set(Tag)
