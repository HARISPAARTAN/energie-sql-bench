from pathlib import Path

import pytest

from energie_sql_bench.taxonomy import auto_labels, export_label_template, label_counts, load_labels


@pytest.mark.parametrize(
    ("expect", "status", "error", "correct", "reason", "labels"),
    [
        ("rows", "ok", None, True, "ok", ()),
        ("rows", "no_sql", "kein SQL-Block", False, "Status no_sql", ("E1",)),
        ("rows", "parse_error", "x", False, "Status parse_error", ("E1",)),
        ("rows", "blocked", None, False, "Status blocked", ("E11",)),
        ("rows", "timeout", "HYT00", False, "Status timeout", ("E13",)),
        ("rows", "truncated", None, False, "abgeschnitten", ("E13",)),
        ("rows", "db_error", "42S22: Invalid column name 'erzeugung_gwh'.", False, "x", ("E2",)),
        ("rows", "db_error", "Binder Error: Referenced column x not found", False, "x", ("E2",)),
        ("rows", "db_error", "42000: Incorrect syntax near 'LIMIT'.", False, "x", ("E1",)),
        ("rows", "abstain", None, False, "Enthaltung statt Antwort", ("E12",)),
        ("abstain", "ok", None, False, "beantwortet statt enthalten", ("E12",)),
        ("rows", "ok", None, False, "zu wenige Spalten (1 statt 2)", ("E10",)),
        ("rows", "ok", None, False, "Werte stimmen nicht überein", ("E?",)),
        ("rows", "provider_error", "overloaded", False, "Status provider_error", ("E0",)),
    ],
)
def test_auto_labels(expect, status, error, correct, reason, labels) -> None:  # noqa: ANN001
    assert auto_labels(expect, status, error, correct, reason) == labels


def test_label_template_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "labels.csv"
    items = [
        {"item_id": "q001-de", "repeat": 0, "labels": ["E?"]},
        {"item_id": "q002-de", "repeat": 0, "labels": ["E2"]},
        {"item_id": "q003-en", "repeat": 0, "labels": []},
    ]
    assert export_label_template(path, "run-a", items) == 1
    assert export_label_template(path, "run-a", items) == 0
    text = path.read_text(encoding="utf-8")
    assert text.startswith("run_id,item_id,repeat,label,note\n")
    path.write_text(
        text.replace("run-a,q001-de,0,,", "run-a,q001-de,0,E5,UTC statt Ortszeit"), encoding="utf-8"
    )
    manual = load_labels(path)
    assert manual == {("run-a", "q001-de", 0): "E5"}
    assert label_counts("run-a", items, manual) == {"E2": 1, "E5": 1}
