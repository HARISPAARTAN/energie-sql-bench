"""Gold result sets: build and verify (esb gold build), write, load."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from energie_sql_bench.compare import compare
from energie_sql_bench.config import CompareSettings
from energie_sql_bench.execute import Executor
from energie_sql_bench.files import read_json, write_json
from energie_sql_bench.guard import check_sql
from energie_sql_bench.questions import Question, tables_in_sql, tolerance_for
from energie_sql_bench.resultset import ResultSet, encode_value


@dataclass(frozen=True)
class GoldEntry:
    id: str
    expect: str
    result: ResultSet | None
    sql_sha256: str | None
    snapshot: str

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "expect": self.expect,
            "result": self.result.to_json() if self.result is not None else None,
            "snapshot": self.snapshot,
            "sql_sha256": self.sql_sha256,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> GoldEntry:
        result = ResultSet.from_json(data["result"]) if data.get("result") is not None else None
        return cls(data["id"], data["expect"], result, data.get("sql_sha256"), data["snapshot"])


def sql_sha256(sql: str) -> str:
    return hashlib.sha256(sql.strip().encode("utf-8")).hexdigest()


def canonical_rows(result: ResultSet) -> ResultSet:
    """Rows in a fixed order, for unordered intents: the engine may return them in any order, the file must not churn."""

    def key(row: list[Any]) -> str:
        return json.dumps([encode_value(v) for v in row], ensure_ascii=False)

    return ResultSet(result.columns, result.types, sorted(result.rows, key=key), result.truncated)


def stale_gold(gold: dict[str, GoldEntry], digest: str) -> list[str]:
    """Ids of gold files that were frozen against a different snapshot digest."""
    return sorted(qid for qid, entry in gold.items() if entry.snapshot != digest)


def _verify(
    q: Question, executor: Executor, max_rows: int, cmp: CompareSettings
) -> tuple[ResultSet | None, list[str]]:
    problems: list[str] = []
    for label, sql in (("gold_sql", q.gold_sql), ("check_sql", q.check_sql)):
        verdict = check_sql(sql)
        if not verdict.allowed:
            problems.append(f"{q.id}: {label} vom Guard blockiert: {verdict.reason}")
    if problems:
        return None, problems
    expected_tables = tables_in_sql(q.gold_sql or "")
    if sorted(q.tables) != expected_tables:
        problems.append(f"{q.id}: tables muss {expected_tables} sein")
    first = executor.run(q.gold_sql or "")
    if not first.ok or first.result is None:
        problems.append(f"{q.id}: gold_sql fehlgeschlagen: {first.error}")
        return None, problems
    second = executor.run(q.gold_sql or "")
    result = first.result if q.ordered else canonical_rows(first.result)
    again = None if second.result is None else (second.result if q.ordered else canonical_rows(second.result))
    if not second.ok or again is None or again.to_json() != result.to_json():
        problems.append(f"{q.id}: gold_sql nicht reproduzierbar")
    if result.truncated or len(result.rows) > max_rows:
        problems.append(f"{q.id}: mehr als {max_rows} Zeilen")
    if not result.rows:
        problems.append(f"{q.id}: leeres Gold-Ergebnis")
    check = executor.run(q.check_sql or "")
    if not check.ok or check.result is None:
        problems.append(f"{q.id}: check_sql fehlgeschlagen: {check.error}")
    else:
        rel, abs_ = tolerance_for(q, cmp)
        verdict_cmp = compare(result, check.result, q.ordered, rel, abs_)
        if not (verdict_cmp.match and verdict_cmp.strict):
            problems.append(f"{q.id}: Gegenprobe weicht ab: {verdict_cmp.reason}")
    return result, problems


def build_gold(
    questions: Iterable[Question],
    executor: Executor,
    snapshot_digest: str,
    max_rows: int,
    compare: CompareSettings,
) -> tuple[dict[str, GoldEntry], list[str]]:
    entries: dict[str, GoldEntry] = {}
    errors: list[str] = []
    for q in questions:
        if q.expect == "abstain":
            entries[q.id] = GoldEntry(q.id, "abstain", None, None, snapshot_digest)
            continue
        result, problems = _verify(q, executor, max_rows, compare)
        if problems:
            errors.extend(problems)
            continue
        entries[q.id] = GoldEntry(q.id, "rows", result, sql_sha256(q.gold_sql or ""), snapshot_digest)
    return entries, errors


def write_gold(entries: dict[str, GoldEntry], directory: Path) -> None:
    for entry in entries.values():
        write_json(directory / f"{entry.id}.json", entry.to_json())


def load_gold(directory: Path) -> dict[str, GoldEntry]:
    return {path.stem: GoldEntry.from_json(read_json(path)) for path in sorted(directory.glob("q*.json"))}
