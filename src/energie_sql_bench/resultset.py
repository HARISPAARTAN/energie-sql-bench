"""Result sets with an exact JSON encoding: decimals as strings, dates and timestamps as ISO text."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, Decimal):
        return "decimal"
    if isinstance(value, float):
        return "float"
    if isinstance(value, dt.datetime):
        return "datetime"
    if isinstance(value, dt.date):
        return "date"
    if isinstance(value, dt.time):
        return "time"
    if isinstance(value, bytes | bytearray | memoryview):
        return "bytes"
    return "str"


def infer_types(rows: list[list[Any]], ncols: int) -> list[str]:
    """Column types from the first non-null value of each column."""
    types = ["null"] * ncols
    for row in rows:
        for i, value in enumerate(row):
            if types[i] == "null" and value is not None:
                types[i] = type_name(value)
    return types


def encode_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, dt.datetime):
        return value.isoformat(timespec="seconds") if value.microsecond == 0 else value.isoformat()
    if isinstance(value, dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, bytes | bytearray | memoryview):
        return bytes(value).hex()
    return str(value)


def decode_value(value: Any, type_name: str) -> Any:
    if value is None:
        return None
    if type_name == "decimal":
        return Decimal(value)
    if type_name == "float":
        return float(value)
    if type_name == "int":
        return int(value)
    if type_name == "bool":
        return bool(value)
    if type_name == "datetime":
        return dt.datetime.fromisoformat(value)
    if type_name == "date":
        return dt.date.fromisoformat(value)
    if type_name == "time":
        return dt.time.fromisoformat(value)
    return value


@dataclass(frozen=True)
class ResultSet:
    columns: list[str]
    types: list[str]
    rows: list[list[Any]]
    truncated: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "columns": list(self.columns),
            "types": list(self.types),
            "rows": [[encode_value(v) for v in row] for row in self.rows],
            "truncated": self.truncated,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ResultSet:
        types = list(data["types"])
        rows = [[decode_value(v, types[i]) for i, v in enumerate(row)] for row in data["rows"]]
        return cls(list(data["columns"]), types, rows, bool(data.get("truncated", False)))
