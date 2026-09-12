from chesscoach.ingest.pgn import parse_clock, parse_game, parse_games, split_games


def test_split_games_finds_two_games(sample_pgn_text):
    assert len(split_games(sample_pgn_text)) == 2


def test_parse_clock():
    assert parse_clock("[%clk 0:09:58.5]") == 598.5
    assert parse_clock("[%clk 1:00:00]") == 3600.0
    assert parse_clock("no clock here") is None


def test_parse_game_headers_moves_and_clocks(sample_pgn_text):
    game = parse_games(sample_pgn_text)[0]
    assert game.headers["White"] == "coachtest"
    assert game.headers["Link"] == "https://www.chess.com/game/live/100000000001"
    assert game.result == "1-0"
    assert game.ply_count == 13
    assert [m.san for m in game.moves[:4]] == ["e4", "e5", "Nf3", "d6"]
    assert game.moves[-1].san == "Nd5#"
    assert game.moves[0].clock_seconds == 598.7
    assert game.moves[4].clock_seconds == 591.0  # "0:09:51" sans décimale
    first, second = game.moves[0], game.moves[1]
    assert (first.move_number, first.color) == (1, "white")
    assert (second.move_number, second.color) == (1, "black")
    assert game.pgn.startswith('[Event "Live Chess"]')


def test_parse_game_ignores_variations_nags_and_plain_comments():
    text = '[Result "*"]\n\n1. e4 $1 {bon coup} (1. d4 d5) 1... c5 {[%clk 0:04:59]} 2. Nf3 *'
    game = parse_game(text)
    assert [m.san for m in game.moves] == ["e4", "c5", "Nf3"]
    assert game.moves[0].clock_seconds is None
    assert game.moves[1].clock_seconds == 299.0
    assert game.result == "*"


def test_result_falls_back_to_header_when_movetext_has_none():
    game = parse_game('[Result "0-1"]\n\n1. e4 e5')
    assert game.result == "0-1"
    assert game.ply_count == 2
