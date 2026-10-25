"""Run folder: config.json, responses.jsonl, predictions.jsonl.gz (keyed by SQL hash), summary.json."""

from __future__ import annotations

import gzip
import io
import json
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
    responses = [
        json.loads(line)
        for line in (run_dir / "responses.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    with gzip.open(run_dir / "predictions.jsonl.gz", "rt", encoding="utf-8") as handle:
        predictions = {
            row["sql_sha256"]: row["exec"] for row in (json.loads(line) for line in handle if line.strip())
        }
    return RunFiles(
        read_json(run_dir / "config.json"), responses, predictions, read_json(run_dir / "summary.json")
    )
