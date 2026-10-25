"""Fail-closed statement guard on the sqlglot T-SQL AST.

Allowed: exactly one statement whose root is SELECT, WITH ... SELECT or a set operation of selects, reading
only tables and views in the schemas dw and rpt, calling only built-in functions from an allow-list. Anything
the parser cannot read, and anything nested deeper than the parser can follow, is blocked. check_sql never raises.
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
    "NextValueFor",  # advances a sequence: a write
    "Lock",
    "ForClause",  # FOR XML / FOR JSON / FOR BROWSE
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
        # Every other keyword that starts a T-SQL statement. SQL Server runs a bare one after a SELECT as a
        # second statement ("SELECT 1 COMMIT"), while sqlglot reads it as a column or table alias.
        # SELECT, WITH and FETCH are left out because a query legitimately contains them.
        "ALTER",
        "BEGIN",
        "BREAK",
        "CHECKPOINT",
        "CLOSE",
        "COMMIT",
        "CONTINUE",
        "CREATE",
        "DEALLOCATE",
        "DELETE",
        "DISABLE",
        "DROP",
        "DUMP",
        "ENABLE",
        "GET",
        "GOTO",
        "IF",
        "INSERT",
        "LOAD",
        "MERGE",
        "MOVE",
        "OPEN",
        "PRINT",
        "RAISERROR",
        "READTEXT",
        "RECEIVE",
        "RETURN",
        "REVERT",
        "ROLLBACK",
        "SAVE",
        "SEND",
        "SET",
        "SETUSER",
        "THROW",
        "TRUNCATE",
        "UPDATE",
        "UPDATETEXT",
        "WHILE",
        "WRITETEXT",
    }
)

# Reserved keywords of T-SQL (plus the ODBC and future ones): an unquoted alias may not be one of them.
_RESERVED_WORDS = frozenset(
    """
    ADD ALL ALTER AND ANY AS ASC AUTHORIZATION BACKUP BEGIN BETWEEN BREAK BROWSE BULK BY CASCADE CASE CHECK
    CHECKPOINT CLOSE CLUSTERED COALESCE COLLATE COLUMN COMMIT COMPUTE CONSTRAINT CONTAINS CONTAINSTABLE CONTINUE
    CONVERT CREATE CROSS CURRENT CURRENT_DATE CURRENT_TIME CURRENT_TIMESTAMP CURRENT_USER CURSOR DATABASE DBCC
    DEALLOCATE DECLARE DEFAULT DELETE DENY DESC DISK DISTINCT DISTRIBUTED DOUBLE DROP DUMP ELSE END ERRLVL ESCAPE
    EXCEPT EXEC EXECUTE EXISTS EXIT EXTERNAL FETCH FILE FILLFACTOR FOR FOREIGN FREETEXT FREETEXTTABLE FROM FULL
    FUNCTION GOTO GRANT GROUP HAVING HOLDLOCK IDENTITY IDENTITY_INSERT IDENTITYCOL IF IN INDEX INNER INSERT
    INTERSECT INTO IS JOIN KEY KILL LEFT LIKE LINENO LOAD MERGE NATIONAL NOCHECK NONCLUSTERED NOT NULL NULLIF OF
    OFF OFFSETS ON OPEN OPENDATASOURCE OPENQUERY OPENROWSET OPENXML OPTION OR ORDER OUTER OVER PERCENT PIVOT PLAN
    PRECISION PRIMARY PRINT PROC PROCEDURE PUBLIC RAISERROR READ READTEXT RECONFIGURE REFERENCES REPLICATION
    RESTORE RESTRICT RETURN REVERT REVOKE RIGHT ROLLBACK ROWCOUNT ROWGUIDCOL RULE SAVE SCHEMA SECURITYAUDIT SELECT
    SEMANTICKEYPHRASETABLE SEMANTICSIMILARITYDETAILSTABLE SEMANTICSIMILARITYTABLE SESSION_USER SET SETUSER
    SHUTDOWN SOME STATISTICS SYSTEM_USER TABLE TABLESAMPLE TEXTSIZE THEN TO TOP TRAN TRANSACTION TRIGGER TRUNCATE
    TRY_CONVERT TSEQUAL UNION UNIQUE UNPIVOT UPDATE UPDATETEXT USE USER VALUES VARYING VIEW WAITFOR WHEN WHERE
    WHILE WITH WITHIN WRITETEXT
    """.split()
)

# Names that may not be followed by a dot: system catalogs, dbo objects and schema-qualified functions.
_DENIED_QUALIFIERS = frozenset({"sys", "information_schema", "dbo", "guest"})

# Built-in functions that sqlglot parses into a typed node, by class name. Everything else is blocked.
_ALLOWED_TYPED_FUNCTIONS = frozenset(
    """
    Abs Acos And ApproxDistinct Ascii Asin Atan Atan2 Avg Case Cast Ceil Chr Coalesce Collate Concat ConcatWs
    Convert Cos Cot Count CumeDist CurrentTimestamp CurrentTimestampLTZ DateAdd DateDiff DateFromParts Day Degrees
    DenseRank Exists Exp Extract FirstValue Floor Greatest GroupConcat Grouping GroupingId If Lag LastDay LastValue
    Lead Least Left Length Ln Log Lower Max Min Month Ntile Nullif NumberToStr Or PercentRank PercentileCont
    PercentileDisc Pi Pow Radians Rank Repeat Replace Reverse Right Round RowNumber Sign Sin Soundex Space Sqrt
    Stddev StrPosition Stuff Substring Sum Tan TimeFromParts TimeStrToTime TimeToStr TimestampFromParts
    TimestampTrunc Translate Trim TryCast TsOrDsToDate Unicode Upper Year
    """.split()
)

# Built-in functions that sqlglot does not know (parsed as Anonymous), lower case.
_ALLOWED_ANONYMOUS_FUNCTIONS = frozenset(
    """
    choose count_big datalength date_bucket datediff_big datetime2fromparts datetimefromparts datetimeoffsetfromparts
    difference getutcdate isdate isnumeric nchar patindex quotename smalldatetimefromparts stdev stdevp str
    switchoffset sysdatetimeoffset sysutcdatetime todatetimeoffset var varp
    """.split()
)

# Table hints that take no locks. Everything else (TABLOCKX, UPDLOCK, XLOCK, HOLDLOCK, ...) is blocked.
_ALLOWED_TABLE_HINTS = frozenset({"NOLOCK", "READUNCOMMITTED"})

_MAX_NESTING = 40  # parentheses and CASE expressions; the parser is recursive, SQL Server itself stops at 32

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


def _block_function(node: exp.Func) -> str | None:
    """A reason when the function call is not a plain built-in from the allow-list, else None."""
    if isinstance(node, exp.Anonymous):
        name = str(node.name).lower()
        if isinstance(node.parent, exp.Dot):
            return f"schema-qualifizierte Funktion {name} nicht erlaubt"
        if name not in _ALLOWED_ANONYMOUS_FUNCTIONS:
            return f"Funktion {name} nicht erlaubt"
        return None
    if type(node).__name__ not in _ALLOWED_TYPED_FUNCTIONS:
        return f"Funktion {node.sql_name().lower()} nicht erlaubt"
    return None


def _block_token_stream(tokens: list) -> GuardResult | None:
    depth = case_depth = 0
    previous = None
    for token in tokens:
        kind = token.token_type
        if kind == TokenType.L_PAREN:
            depth += 1
        elif kind == TokenType.R_PAREN:
            depth -= 1
        elif kind == TokenType.CASE:
            case_depth += 1
        elif kind == TokenType.END:
            case_depth -= 1
        if depth > _MAX_NESTING or case_depth > _MAX_NESTING:
            return _block(f"zu tief verschachtelt (mehr als {_MAX_NESTING} Ebenen)", parse_error=True)
        if kind == TokenType.DOT and previous is not None and previous.text.lower() in _DENIED_QUALIFIERS:
            return _block(f"Objekte oder Funktionen mit Präfix {previous.text.lower()}. nicht erlaubt")
        previous = token
        if kind in _STRING_TOKENS:
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
    return None


def _block_node(node: exp.Expression) -> str | None:
    """A reason when this AST node is not allowed, else None."""
    if isinstance(node, _DENIED_NODES):
        return f"{type(node).__name__} nicht erlaubt"
    if isinstance(node, exp.Func):
        return _block_function(node)
    if node.args.get("options"):  # Select, Union, Intersect, Except: OPTION lifts MAXRECURSION and more
        return "Abfragehinweise (OPTION) nicht erlaubt"
    if isinstance(node, exp.Lateral) and not isinstance(node.this, exp.Subquery):
        return "APPLY und LATERAL sind nur mit einer Unterabfrage erlaubt"
    if isinstance(node, exp.WithTableHint):
        for hint in node.expressions:
            if str(hint.name).upper() not in _ALLOWED_TABLE_HINTS:
                return f"Tabellenhinweis {hint.name} nicht erlaubt (nur NOLOCK oder READUNCOMMITTED)"
    if isinstance(node, exp.Alias | exp.TableAlias):
        names = (
            [node.args.get("alias")]
            if isinstance(node, exp.Alias)
            else [node.this, *(node.args.get("columns") or [])]
        )
        for name in names:
            if (
                isinstance(name, exp.Identifier)
                and not name.quoted
                and str(name.this).upper() in _RESERVED_WORDS
            ):
                return f"reserviertes Wort {str(name.this).upper()} als Alias nicht erlaubt"
    return None


def check_sql(sql: str | None, allowed_schemas: frozenset[str] = ALLOWED_SCHEMAS) -> GuardResult:
    """Never raises: anything unexpected, including a RecursionError from the parser, is a block."""
    try:
        return _check_sql(sql, allowed_schemas)
    except Exception as exc:  # fail closed, e.g. RecursionError on pathological nesting
        return _block(f"nicht prüfbar: {type(exc).__name__}", parse_error=True)


def _check_sql(sql: str | None, allowed_schemas: frozenset[str]) -> GuardResult:
    if sql is None or not sql.strip():
        return _block("leere Anweisung")
    try:
        tokens = sqlglot.tokenize(sql, read="tsql")
    except SqlglotError as exc:
        return _block(f"nicht als T-SQL lesbar: {str(exc).splitlines()[0]}", parse_error=True)
    blocked = _block_token_stream(tokens)
    if blocked is not None:
        return blocked
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
        reason = _block_node(node)
        if reason is not None:
            return _block(reason)
    cte_names = {cte.alias_or_name.lower() for cte in root.find_all(exp.CTE)}
    tables: set[str] = set()
    for table in root.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            return _block("Tabellenfunktionen und Tabellenausdrücke nicht erlaubt")
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
