"""Error taxonomy: automatic labels E0, E1, E2, E10, E11, E12, E13; manual labels (E3 to E9) from analysis/labels.csv."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any

AUTO_LABELS = frozenset({"E0", "E1", "E2", "E10", "E11", "E12", "E13"})
MANUAL_LABELS = frozenset({"E3", "E4", "E5", "E6", "E7", "E8", "E9"})
UNLABELLED = "E?"
HEADER = ["run_id", "item_id", "repeat", "label", "note"]
E2_PATTERNS = (
    "invalid column name",
    "invalid object name",
    "binder error",
    "does not exist",
    "not found",
    "ungültiger spaltenname",
    "ungültiger objektname",
)


def auto_labels(expect: str, status: str, error: str | None, correct: bool, reason: str) -> tuple[str, ...]:
    if correct:
        return ()
    if status == "provider_error":
        return ("E0",)
    if status in ("no_sql", "parse_error"):
        return ("E1",)
    if status == "blocked":
        return ("E11",)
    if status in ("timeout", "truncated"):
        return ("E13",)
    if status == "db_error":
        text = (error or "").lower()
        return ("E2",) if any(p in text for p in E2_PATTERNS) else ("E1",)
    if status == "abstain" or expect == "abstain":
        return ("E12",)
    if reason.startswith("zu wenige Spalten"):
        return ("E10",)
    return (UNLABELLED,)


def load_labels(path: Path) -> dict[tuple[str, str, int], str]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            (row["run_id"], row["item_id"], int(row["repeat"])): row["label"].strip()
            for row in csv.DictReader(handle)
            if row["label"].strip()
        }


def export_label_template(path: Path, run_id: str, items: list[dict[str, Any]]) -> int:
    """Append one empty row per unlabelled wrong item of the run; returns the number of new rows."""
    existing: set[tuple[str, str, int]] = set()
    rows: list[list[str]] = []
    if path.is_file():
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                existing.add((row["run_id"], row["item_id"], int(row["repeat"])))
                rows.append([row[h] for h in HEADER])
    added = 0
    for item in items:
        key = (run_id, item["item_id"], int(item["repeat"]))
        if UNLABELLED in item["labels"] and key not in existing:
            rows.append([run_id, item["item_id"], str(item["repeat"]), "", ""])
            existing.add(key)
            added += 1
    rows.sort(key=lambda r: (r[0], r[1], int(r[2])))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(HEADER)
        writer.writerows(rows)
    return added


def label_counts(
    run_id: str, items: list[dict[str, Any]], manual: dict[tuple[str, str, int], str]
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in items:
        for label in item["labels"]:
            if label == UNLABELLED:
                label = manual.get((run_id, item["item_id"], int(item["repeat"])), UNLABELLED)
            counts[label] += 1
    return dict(sorted(counts.items()))
