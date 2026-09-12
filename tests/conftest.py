from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_pgn_text() -> str:
    return (FIXTURES / "sample_chesscom.pgn").read_text(encoding="utf-8")
