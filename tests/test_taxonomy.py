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


def test_tags_without_lichess_theme_are_documented():
    # Ces deux tags n'ont aucun thème Lichess correspondant (D-014) : ils sont servis par la
    # position rejouée, pas par des puzzles. Tout autre tag vide serait une régression du mapping.
    assert {t for t, themes in LICHESS_THEMES.items() if not themes} == {Tag.TIME_PRESSURE, Tag.UNNECESSARY_EXCHANGE}
