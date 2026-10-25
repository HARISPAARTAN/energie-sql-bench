"""Execution-based result comparison: multisets of rows, best column assignment, numeric tolerance.

Values are normalised before comparison: numbers (int, bool, float, Decimal) to Decimal; dates and timestamps
to ISO text (a timestamp at midnight equals its date); strings to NFC, trimmed and case-folded, with ISO-like
date strings parsed. Column names are ignored. Unordered comparison sorts rows by a type-aware key; two rows
whose leading numbers differ by less than the tolerance but whose other cells differ can sort apart, an
accepted edge case documented in docs/methodology.md.
"""

from __future__ import annotations

import datetime as dt
import math
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from energie_sql_bench.resultset import ResultSet

_ISO = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?)?$")
_SEARCH_BUDGET = 20000


@dataclass(frozen=True)
class Comparison:
    match: bool
    strict: bool
    reason: str
    extra_columns: int = 0


def _iso(date: str, hh: str | None, mm: str | None, ss: str | None) -> str:
    if hh is None or (hh, mm, ss or "00") == ("00", "00", "00"):
        return date
    return f"{date}T{hh}:{mm}:{ss or '00'}"


def normalize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ("float", repr(value))
        return Decimal(repr(value))
    if isinstance(value, dt.datetime):
        v = value.replace(tzinfo=None)
        return _iso(v.date().isoformat(), f"{v.hour:02d}", f"{v.minute:02d}", f"{v.second:02d}")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, dt.time):
        return value.isoformat(timespec="seconds")
    if isinstance(value, bytes | bytearray | memoryview):
        return bytes(value).hex()
    text = unicodedata.normalize("NFC", str(value)).strip()
    match = _ISO.match(text)
    if match:
        return _iso(*match.groups())
    return text.casefold()


def values_equal(a: Any, b: Any, rel_tol: float, abs_tol: float) -> bool:
    if a is None or b is None:
        return a is None and b is None
    a_num, b_num = isinstance(a, Decimal), isinstance(b, Decimal)
    if a_num and b_num:
        diff = abs(a - b)
        return diff <= Decimal(str(abs_tol)) or diff <= Decimal(str(rel_tol)) * max(abs(a), abs(b))
    if a_num or b_num:
        return False
    return a == b


def _cell_key(value: Any) -> tuple:
    if value is None:
        return (0, 0.0, "")
    if isinstance(value, Decimal):
        return (1, float(value), "")
    if isinstance(value, str):
        return (2, 0.0, value)
    return (3, 0.0, repr(value))


def _row_key(row: list[Any]) -> tuple:
    return tuple(_cell_key(v) for v in row)


def _rows_match(gold: list[list[Any]], pred: list[list[Any]], ordered: bool, rel: float, abs_: float) -> bool:
    if len(gold) != len(pred):
        return False
    if not ordered:
        gold = sorted(gold, key=_row_key)
        pred = sorted(pred, key=_row_key)
    return all(
        all(values_equal(a, b, rel, abs_) for a, b in zip(g, p, strict=True))
        for g, p in zip(gold, pred, strict=True)
    )


def _column_compatible(
    gold_col: list[Any], pred_col: list[Any], ordered: bool, rel: float, abs_: float
) -> bool:
    if not ordered:
        gold_col = sorted(gold_col, key=_cell_key)
        pred_col = sorted(pred_col, key=_cell_key)
    return all(values_equal(a, b, rel, abs_) for a, b in zip(gold_col, pred_col, strict=True))


def compare(
    gold: ResultSet, pred: ResultSet, ordered: bool = False, rel_tol: float = 1e-4, abs_tol: float = 0.005
) -> Comparison:
    if pred.truncated:
        return Comparison(False, False, "Vorhersage abgeschnitten (Zeilenlimit)")
    k, m = len(gold.columns), len(pred.columns)
    if m < k:
        return Comparison(False, False, f"zu wenige Spalten ({m} statt {k})")
    extra = m - k
    if len(gold.rows) != len(pred.rows):
        return Comparison(False, False, f"Zeilenzahl {len(pred.rows)} statt {len(gold.rows)}", extra)
    g = [[normalize(v) for v in row] for row in gold.rows]
    p = [[normalize(v) for v in row] for row in pred.rows]
    gold_cols = [[row[i] for row in g] for i in range(k)]
    pred_cols = [[row[j] for row in p] for j in range(m)]
    candidates = [
        [j for j in range(m) if _column_compatible(gold_cols[i], pred_cols[j], ordered, rel_tol, abs_tol)]
        for i in range(k)
    ]
    for i, options in enumerate(candidates):
        if not options:
            return Comparison(False, False, f"keine passende Spalte für Gold-Spalte {gold.columns[i]}", extra)
    order = sorted(range(k), key=lambda i: len(candidates[i]))
    assignment: dict[int, int] = {}
    budget = [_SEARCH_BUDGET]

    def search(pos: int) -> bool:
        if budget[0] <= 0:
            return False
        budget[0] -= 1
        if pos == k:
            projected = [[row[assignment[i]] for i in range(k)] for row in p]
            return _rows_match(g, projected, ordered, rel_tol, abs_tol)
        i = order[pos]
        used = set(assignment.values())
        for j in candidates[i]:
            if j in used:
                continue
            assignment[i] = j
            if search(pos + 1):
                return True
            del assignment[i]
        return False

    if search(0):
        return Comparison(True, extra == 0, "ok", extra)
    return Comparison(False, False, "Werte stimmen nicht überein", extra)


def is_empty_result(result: ResultSet | None) -> bool:
    """True for a result without rows or whose cells are all NULL (counts as abstention for 'abstain' items)."""
    if result is None:
        return False
    return all(v is None for row in result.rows for v in row)
