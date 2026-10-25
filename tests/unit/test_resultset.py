import datetime as dt
from decimal import Decimal

from energie_sql_bench.resultset import ResultSet, decode_value, encode_value, infer_types, type_name


def test_type_names() -> None:
    assert type_name(None) == "null"
    assert type_name(True) == "bool"
    assert type_name(3) == "int"
    assert type_name(Decimal("1.5")) == "decimal"
    assert type_name(1.5) == "float"
    assert type_name(dt.datetime(2025, 1, 1, 12)) == "datetime"
    assert type_name(dt.date(2025, 1, 1)) == "date"
    assert type_name("x") == "str"


def test_infer_types_uses_first_non_null() -> None:
    assert infer_types([[None, "a"], [Decimal("1"), "b"]], 2) == ["decimal", "str"]
    assert infer_types([], 2) == ["null", "null"]


def test_decimal_encoding_has_no_exponent() -> None:
    assert encode_value(Decimal("1E+3")) == "1000"
    assert encode_value(Decimal("78.512033")) == "78.512033"


def test_roundtrip_all_types() -> None:
    rows = [
        [
            Decimal("1.250"),
            2,
            1.5,
            True,
            dt.date(2025, 10, 26),
            dt.datetime(2025, 10, 4, 21, 0),
            "Bayern",
            None,
        ]
    ]
    rs = ResultSet(["a", "b", "c", "d", "e", "f", "g", "h"], infer_types(rows, 8), rows)
    again = ResultSet.from_json(rs.to_json())
    assert again == rs
    assert rs.to_json()["rows"][0][0] == "1.250"
    assert rs.to_json()["rows"][0][5] == "2025-10-04T21:00:00"


def test_decode_null() -> None:
    assert decode_value(None, "decimal") is None
