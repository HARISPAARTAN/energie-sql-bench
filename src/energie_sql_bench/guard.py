"""Fail-closed statement guard on the sqlglot T-SQL AST.

Allowed: exactly one statement whose root is SELECT, WITH ... SELECT or a set operation of selects, reading
only tables and views in the schemas dw and rpt. Anything the parser cannot read is blocked.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.tokens import TokenType

ALLOWED_SCHEMAS = frozenset({"dw", "rpt"})

_ALLOWED_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except)

_DENIED_NODE_NAMES = (
    "Insert",
    "Update",
    "Delete",
    "Merge",
    "Create",
    "Drop",
    "Alter",
    "AlterTable",
    "TruncateTable",
    "Command",
    "Into",
    "Set",
    "Use",
    "Transaction",
    "Commit",
    "Rollback",
    "Declare",
    "Grant",
    "Revoke",
    "Parameter",
    "SessionParameter",
    "Placeholder",
    "Copy",
    "LoadData",
    "Pragma",
    "Kill",
)
_DENIED_NODES = tuple(
    node for node in (getattr(exp, name, None) for name in _DENIED_NODE_NAMES) if isinstance(node, type)
)

_DENIED_WORDS = frozenset(
    {
        "EXEC",
        "EXECUTE",
        "WAITFOR",
        "SHUTDOWN",
        "KILL",
        "RECONFIGURE",
        "DBCC",
        "BACKUP",
        "RESTORE",
        "GRANT",
        "REVOKE",
        "DENY",
        "OPENROWSET",
        "OPENQUERY",
        "OPENDATASOURCE",
        "OPENXML",
        "BULK",
        "GO",
        "USE",
        "DECLARE",
    }
)

_DENIED_FUNCTIONS = frozenset(
    {
        "current_user",  # sqlglot parses SUSER_SNAME() as CurrentUser
        "session_user",
        "openrowset",
        "openquery",
        "opendatasource",
        "openxml",
        "object_definition",
        "suser_sname",
        "suser_name",
        "system_user",
        "user_name",
        "host_name",
        "db_name",
        "serverproperty",
        "databasepropertyex",
        "is_srvrolemember",
        "has_perms_by_name",
        "fn_dblog",
    }
)

_STRING_TOKENS = frozenset(
    token
    for token in (
        getattr(TokenType, name, None)
        for name in (
            "STRING",
            "NATIONAL_STRING",
            "RAW_STRING",
            "BIT_STRING",
            "HEX_STRING",
            "BYTE_STRING",
            "UNICODE_STRING",
        )
    )
    if token is not None
)


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    reason: str
    tables: tuple[str, ...] = ()
    parse_error: bool = False


def _block(reason: str, parse_error: bool = False) -> GuardResult:
    return GuardResult(False, reason, (), parse_error)


def _function_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    return node.sql_name().lower()


def check_sql(sql: str | None, allowed_schemas: frozenset[str] = ALLOWED_SCHEMAS) -> GuardResult:
    if sql is None or not sql.strip():
        return _block("leere Anweisung")
    try:
        tokens = sqlglot.tokenize(sql, read="tsql")
    except SqlglotError as exc:
        return _block(f"nicht als T-SQL lesbar: {str(exc).splitlines()[0]}", parse_error=True)
    for token in tokens:
        if token.token_type in _STRING_TOKENS:
            continue
        text = token.text
        if text.upper() in _DENIED_WORDS:
            return _block(f"Schlüsselwort {text.upper()} nicht erlaubt")
        if text.lower().startswith(("xp_", "sp_")):
            return _block(f"Systemprozedur {text} nicht erlaubt")
        if text.startswith("@"):
            return _block("Variablen und @@-Systemwerte nicht erlaubt")
        if text.startswith("#"):
            return _block("temporäre Tabellen nicht erlaubt")
    try:
        statements = [s for s in sqlglot.parse(sql, read="tsql") if s is not None]
    except SqlglotError as exc:
        return _block(f"nicht als T-SQL lesbar: {str(exc).splitlines()[0]}", parse_error=True)
    if len(statements) != 1:
        return _block("genau eine Anweisung erlaubt")
    root = statements[0]
    if not isinstance(root, _ALLOWED_ROOTS):
        return _block(f"nur SELECT erlaubt, gefunden: {root.key.upper()}")
    for node in root.walk():
        if isinstance(node, _DENIED_NODES):
            return _block(f"{type(node).__name__} nicht erlaubt")
        if isinstance(node, exp.Func):
            name = _function_name(node)
            if name in _DENIED_FUNCTIONS or name.startswith(("xp_", "sp_")):
                return _block(f"Funktion {name} nicht erlaubt")
    cte_names = {cte.alias_or_name.lower() for cte in root.find_all(exp.CTE)}
    tables: set[str] = set()
    for table in root.find_all(exp.Table):
        name = str(table.name).lower()
        schema = str(table.db).lower()
        if not schema and name in cte_names:
            continue
        if table.catalog:
            return _block(f"Datenbank- oder Servernamen nicht erlaubt: {table.sql(dialect='tsql')}")
        if not name:
            return _block("Tabellenausdruck nicht erlaubt")
        if not schema:
            return _block(f"Tabelle {table.name} ohne Schema: dw. oder rpt. voranstellen")
        if schema not in allowed_schemas:
            return _block(f"Schema {table.db} nicht erlaubt (nur dw und rpt)")
        tables.add(f"{schema}.{name}")
    return GuardResult(True, "ok", tuple(sorted(tables)))
