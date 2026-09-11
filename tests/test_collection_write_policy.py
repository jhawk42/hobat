from __future__ import annotations

import json
from pathlib import Path

import pytest

from util_data import (
    CollectionWriteOutcome,
    save_checkpoint_json,
    save_final_json,
)


@pytest.mark.parametrize(
    ("payload", "outcome", "expected"),
    [
        ([], CollectionWriteOutcome.complete(valid_empty_reason="confirmed-empty"), []),
        (["fresh"], CollectionWriteOutcome.complete(), ["fresh"]),
        (["fresh-partial"], CollectionWriteOutcome.partial(has_usable_data=True), ["fresh-partial"]),
        ([], CollectionWriteOutcome.partial(has_usable_data=False), ["old"]),
        ([], CollectionWriteOutcome.failed(), ["old"]),
    ],
)
def test_final_write_requires_complete_or_usable_partial_outcome(
    tmp_path: Path, payload: list[str], outcome: CollectionWriteOutcome, expected: list[str]
) -> None:
    target = tmp_path / "final.json"
    target.write_text('["old"]', encoding="utf-8")

    save_final_json(payload, target, outcome)

    assert json.loads(target.read_text(encoding="utf-8")) == expected


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (CollectionWriteOutcome.complete(), ["old"]),
        (CollectionWriteOutcome.partial(has_usable_data=True), []),
        (CollectionWriteOutcome.partial(has_usable_data=False), ["old"]),
        (CollectionWriteOutcome.failed(), ["old"]),
    ],
)
def test_checkpoint_write_requires_usable_partial_data(
    tmp_path: Path, outcome: CollectionWriteOutcome, expected: list[str]
) -> None:
    target = tmp_path / "checkpoint.partial.json"
    target.write_text('["old"]', encoding="utf-8")

    save_checkpoint_json([], target, outcome)

    assert json.loads(target.read_text(encoding="utf-8")) == expected