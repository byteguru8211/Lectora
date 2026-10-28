"""Narration timing: blocks keep the pauses of the original video."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.translation import NarrationBlock, TranslationService


def test_short_gaps_are_read_through():
    blocks = TranslationService()._narration_blocks(
        [
            (0.0, 3.0, "Первая фраза."),
            (3.2, 6.0, "Вторая фраза."),
        ]
    )
    assert blocks == [NarrationBlock(0.0, 6.0, "Первая фраза. Вторая фраза.")]


def test_long_silence_starts_a_new_block():
    blocks = TranslationService()._narration_blocks(
        [
            (0.0, 3.0, "До заставки."),
            (12.0, 15.0, "После заставки."),
        ]
    )
    assert [block.start for block in blocks] == [0.0, 12.0]
    assert [block.end for block in blocks] == [3.0, 15.0]


def test_empty_translations_are_skipped():
    blocks = TranslationService()._narration_blocks(
        [
            (0.0, 2.0, ""),
            (2.0, 4.0, "   "),
            (4.0, 6.0, "Речь."),
        ]
    )
    assert blocks == [NarrationBlock(4.0, 6.0, "Речь.")]


def test_tempo_only_speeds_up_and_chains_above_two():
    assert TranslationService._tempo_filters(0.8) == []
    assert TranslationService._tempo_filters(1.0) == []
    assert TranslationService._tempo_filters(1.25) == ["atempo=1.2500"]
    assert TranslationService._tempo_filters(3.0) == ["atempo=2.0", "atempo=1.5000"]
