"""Run folder: config.json, responses.jsonl, predictions.jsonl.gz (keyed by SQL hash), summary.json.

JSON lines are split on LF only: str.splitlines() would also split on U+0085, U+2028 and U+2029, which
json.dumps(ensure_ascii=False) writes raw, and a model response can contain them."""

from __future__ import annotations

import gzip
import io
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from energie_sql_bench.files import read_json, write_json, write_text


@dataclass(frozen=True)
class RunFiles:
    config: dict[str, Any]
    responses: list[dict[str, Any]]
    predictions: dict[str, dict[str, Any]]
    summary: dict[str, Any]


def _line(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n"


def parse_lines(text: str, tolerate_torn_tail: bool = False) -> list[dict[str, Any]]:
    """Parse JSON lines, split on LF only. A last line that does not parse (a process killed mid-write, so
    the text has no final newline) is dropped only when tolerate_torn_tail is set; any other bad line raises."""
    lines = text.split("\n")
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            if tolerate_torn_tail and number == len(lines) - 1:
                break
            raise
    return rows


def read_lines(path: Path, tolerate_torn_tail: bool = False) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="\n") as handle:
        return parse_lines(handle.read(), tolerate_torn_tail)


class Journal:
    """Crash-safe record of a live run: config.json plus one appended, fsynced line per provider response.
    A run that dies (Ctrl+C, an adapter bug) leaves every response it paid for on disk and can be resumed."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.config_path = directory / "config.json"
        self.responses_path = directory / "responses.jsonl"

    def exists(self) -> bool:
        return self.config_path.is_file()

    def start(self, config: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        write_json(self.config_path, config)
        if not self.responses_path.exists():
            write_text(self.responses_path, "")

    def load(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """(config, responses). A torn last line is removed from the file so that appending is safe."""
        rows = (
            read_lines(self.responses_path, tolerate_torn_tail=True) if self.responses_path.is_file() else []
        )
        write_text(self.responses_path, "".join(_line(r) for r in rows))
        return read_json(self.config_path), rows

    def append(self, row: dict[str, Any]) -> None:
        with self.responses_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(_line(row))
            handle.flush()
            os.fsync(handle.fileno())

    def discard(self) -> None:
        for path in (self.responses_path, self.config_path):
            path.unlink(missing_ok=True)
        try:
            self.directory.rmdir()
        except OSError:
            pass


def write_run(
    run_dir: Path,
    config: dict[str, Any],
    responses: list[dict[str, Any]],
    predictions: dict[str, dict[str, Any]],
    summary: dict[str, Any],
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "config.json", config)
    write_text(run_dir / "responses.jsonl", "".join(_line(r) for r in responses))
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0) as gz:
        for sha in sorted(predictions):
            gz.write(_line({"exec": predictions[sha], "sql_sha256": sha}).encode("utf-8"))
    (run_dir / "predictions.jsonl.gz").write_bytes(buffer.getvalue())
    write_json(run_dir / "summary.json", summary)


def read_run(run_dir: Path) -> RunFiles:
    if not (run_dir / "config.json").is_file():
        raise FileNotFoundError(f"Lauf nicht gefunden: {run_dir}")
    responses = read_lines(run_dir / "responses.jsonl")
    with gzip.open(run_dir / "predictions.jsonl.gz", "rt", encoding="utf-8", newline="\n") as handle:
        predictions = {row["sql_sha256"]: row["exec"] for row in parse_lines(handle.read())}
    return RunFiles(
        read_json(run_dir / "config.json"), responses, predictions, read_json(run_dir / "summary.json")
    )
