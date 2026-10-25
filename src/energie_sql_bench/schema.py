"""Schema dump from the live database, schema rendering for prompts, deterministic table retrieval (v6)."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from typing import Any

Fetch = Callable[..., list[tuple]]

TABLE_SQL = (
    "SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES "
    "WHERE TABLE_SCHEMA IN ('dw', 'rpt') ORDER BY TABLE_SCHEMA, TABLE_NAME"
)
COLUMN_SQL = (
    "SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, "
    "NUMERIC_SCALE, DATETIME_PRECISION, IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS "
    "WHERE TABLE_SCHEMA IN ('dw', 'rpt') ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION"
)
PK_SQL = (
    "SELECT k.TABLE_SCHEMA, k.TABLE_NAME, k.COLUMN_NAME FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc "
    "JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE k ON k.CONSTRAINT_NAME = tc.CONSTRAINT_NAME "
    "AND k.TABLE_SCHEMA = tc.TABLE_SCHEMA "
    "WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY' AND tc.TABLE_SCHEMA IN ('dw', 'rpt') "
    "ORDER BY k.TABLE_SCHEMA, k.TABLE_NAME, k.ORDINAL_POSITION"
)
FK_SQL = (
    "SELECT fk.TABLE_SCHEMA, fk.TABLE_NAME, cu.COLUMN_NAME, pk.TABLE_SCHEMA, pk.TABLE_NAME, pt.COLUMN_NAME "
    "FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc "
    "JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS fk ON fk.CONSTRAINT_NAME = rc.CONSTRAINT_NAME "
    "JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS pk ON pk.CONSTRAINT_NAME = rc.UNIQUE_CONSTRAINT_NAME "
    "JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE cu ON cu.CONSTRAINT_NAME = rc.CONSTRAINT_NAME "
    "JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE pt ON pt.CONSTRAINT_NAME = rc.UNIQUE_CONSTRAINT_NAME "
    "AND pt.ORDINAL_POSITION = cu.ORDINAL_POSITION "
    "WHERE fk.TABLE_SCHEMA IN ('dw', 'rpt') ORDER BY fk.TABLE_SCHEMA, fk.TABLE_NAME, cu.COLUMN_NAME"
)
VALUE_QUERIES: dict[str, tuple[tuple[str, ...], str]] = {
    "dw.dim_energietraeger": (
        ("name_de", "name_en", "kategorie_de"),
        "SELECT name_de, name_en, kategorie_de FROM dw.dim_energietraeger ORDER BY sortierung",
    ),
    "dw.dim_region": (
        ("smard_code", "name_de", "typ_de"),
        "SELECT smard_code, name_de, typ_de FROM dw.dim_region ORDER BY region_key",
    ),
    "dw.dim_bundesland": (
        ("name_de", "kuerzel"),
        "SELECT name_de, RTRIM(kuerzel) FROM dw.dim_bundesland ORDER BY bundesland_key",
    ),
}

_WORD = re.compile(r"[a-zäöüß0-9]+")


def format_type(data_type: str, char_len: Any, precision: Any, scale: Any, dt_precision: Any) -> str:
    t = str(data_type).lower()
    if t in ("decimal", "numeric"):
        return f"{t}({precision},{scale})"
    if t in ("nvarchar", "varchar", "char", "nchar"):
        return f"{t}({'max' if char_len == -1 else char_len})"
    if t in ("datetime2", "time", "datetimeoffset"):
        return f"{t}({dt_precision})"
    return t


def dump_schema(fetch: Fetch, database: str) -> dict[str, Any]:
    tables: dict[str, dict[str, Any]] = {}
    for schema, name, table_type in fetch(TABLE_SQL):
        tables[f"{schema}.{name}"] = {
            "type": "view" if table_type == "VIEW" else "table",
            "columns": [],
            "primary_key": [],
            "foreign_keys": [],
            "values": None,
        }
    for schema, name, column, data_type, char_len, precision, scale, dt_precision, nullable in fetch(
        COLUMN_SQL
    ):
        tables[f"{schema}.{name}"]["columns"].append(
            {
                "name": column,
                "type": format_type(data_type, char_len, precision, scale, dt_precision),
                "nullable": nullable == "YES",
            }
        )
    for schema, name, column in fetch(PK_SQL):
        tables[f"{schema}.{name}"]["primary_key"].append(column)
    for f_schema, f_table, f_column, p_schema, p_table, p_column in fetch(FK_SQL):
        tables[f"{f_schema}.{f_table}"]["foreign_keys"].append(
            {"column": f_column, "references": f"{p_schema}.{p_table}.{p_column}"}
        )
    for table, (columns, sql) in VALUE_QUERIES.items():
        if table in tables:
            tables[table]["values"] = {
                "columns": list(columns),
                "rows": [[str(v) for v in row] for row in fetch(sql)],
            }
    return {"database": database, "tables": tables}


def render_schema(
    schema: dict[str, Any], descriptions: dict[str, Any], tables: Iterable[str] | None = None
) -> str:
    selected = sorted(tables) if tables is not None else sorted(schema["tables"])
    described = descriptions.get("tables", {})
    lines: list[str] = []
    for name in selected:
        meta = schema["tables"][name]
        desc = described.get(name, {})
        head = f"{name} ({meta['type']})"
        if desc:
            head += f": {desc.get('de', '')} / {desc.get('en', '')}"
        lines.append(head)
        fks = {fk["column"]: fk["references"] for fk in meta["foreign_keys"]}
        column_notes = desc.get("columns") or {}
        for col in meta["columns"]:
            text = f"  - {col['name']} {col['type']}{'' if col['nullable'] else ' NOT NULL'}"
            if col["name"] in fks:
                text += f" -> {fks[col['name']]}"
            if col["name"] in column_notes:
                text += f"  -- {column_notes[col['name']]}"
            lines.append(text)
        if meta["primary_key"]:
            lines.append(f"  primary key: {', '.join(meta['primary_key'])}")
        values = meta.get("values")
        if values:
            rows = "; ".join(" | ".join(row) for row in values["rows"])
            lines.append(f"  values ({' | '.join(values['columns'])}): {rows}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def words(text: str) -> list[str]:
    return _WORD.findall(unicodedata.normalize("NFC", text).lower())


def _matches(keyword: str, tokens: set[str]) -> bool:
    if len(keyword) >= 4:
        return any(token.startswith(keyword) for token in tokens)
    return keyword in tokens


def retrieve_tables(
    question: str, schema: dict[str, Any], descriptions: dict[str, Any], synonyms: dict[str, str]
) -> list[str]:
    """Deterministic keyword and synonym match over table keywords, plus the dimensions the hits reference."""
    tokens = set(words(question))
    lowered = unicodedata.normalize("NFC", question).lower()
    for phrase, canonical in sorted(synonyms.items()):
        if phrase.lower() in lowered:
            tokens |= set(words(canonical))
    selected: set[str] = set()
    for table, meta in sorted(descriptions.get("tables", {}).items()):
        if table in schema["tables"] and any(
            _matches(str(k).lower(), tokens) for k in meta.get("keywords", [])
        ):
            selected.add(table)
    for table in sorted(selected):
        for fk in schema["tables"][table]["foreign_keys"]:
            selected.add(fk["references"].rsplit(".", 1)[0])
    return sorted(selected) if selected else sorted(schema["tables"])
